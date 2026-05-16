// NetworkStack — VPC 조회/생성 + PrivateLink 엔드포인트.
//
// 사용 방식:
//   cdk synth                              # 신규 VPC 생성 (기본)
//   cdk synth -c existingVpcId=vpc-xxxx \
//             -c appSubnetIds=subnet-a,subnet-b \
//             -c dataSubnetIds=subnet-c,subnet-d   # 기존 VPC 재사용
//
// 신규 VPC 구조:
//   - 2 AZ, NAT GW 0개 (모든 외부 호출은 VPC Endpoint 경유)
//   - "App"  서브넷 (PRIVATE_ISOLATED) — ECS 태스크, ALB, CloudFront VPC Origin ENI
//   - "Data" 서브넷 (PRIVATE_ISOLATED) — RDS PostgreSQL
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

export type NetworkStackProps = cdk.StackProps;

export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.IVpc;
  public readonly appSubnets: ec2.SubnetSelection;
  public readonly dataSubnets: ec2.SubnetSelection;
  // 기존 VPC 재사용 모드에서는 운영자가 별도 endpoint SG를 관리하므로 undefined.
  public readonly endpointSecurityGroup?: ec2.ISecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, props);

    const existingVpcId = this.node.tryGetContext("existingVpcId") as string | undefined;
    const isExistingMode = Boolean(existingVpcId);

    if (existingVpcId) {
      // 기존 VPC 재사용 — 서브넷 ID도 명시적으로 받는다.
      const appSubnetIds = parseCsvContext(this.node.tryGetContext("appSubnetIds"));
      const dataSubnetIds = parseCsvContext(this.node.tryGetContext("dataSubnetIds"));
      if (appSubnetIds.length === 0 || dataSubnetIds.length === 0) {
        throw new Error(
          "existingVpcId 사용 시 appSubnetIds와 dataSubnetIds context도 필요합니다 (e.g. -c appSubnetIds=subnet-a,subnet-b).",
        );
      }

      this.vpc = ec2.Vpc.fromVpcAttributes(this, "Vpc", {
        vpcId: existingVpcId,
        // AZ 정보는 fromLookup이 더 정확하나, 명시 모드에선 stack region의 AZ 2개를 가정.
        availabilityZones: [`${this.region}a`, `${this.region}b`],
        privateSubnetIds: [...appSubnetIds, ...dataSubnetIds],
      });

      this.appSubnets = {
        subnets: appSubnetIds.map((sid, i) => ec2.Subnet.fromSubnetId(this, `AppSubnet${i}`, sid)),
      };
      this.dataSubnets = {
        subnets: dataSubnetIds.map((sid, i) => ec2.Subnet.fromSubnetId(this, `DataSubnet${i}`, sid)),
      };
    } else {
      // 신규 VPC 생성 — NAT 없이 모든 egress는 PrivateLink로.
      const vpc = new ec2.Vpc(this, "Vpc", {
        ipAddresses: ec2.IpAddresses.cidr("10.20.0.0/16"),
        maxAzs: 2,
        natGateways: 0,
        subnetConfiguration: [
          { name: "App", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
          { name: "Data", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 28 },
        ],
        // VPC Flow Logs — CloudWatch Logs (NFR-2 관측성).
        flowLogs: {
          all: {
            destination: ec2.FlowLogDestination.toCloudWatchLogs(),
            trafficType: ec2.FlowLogTrafficType.ALL,
          },
        },
      });
      this.vpc = vpc;
      this.appSubnets = vpc.selectSubnets({ subnetGroupName: "App" });
      this.dataSubnets = vpc.selectSubnets({ subnetGroupName: "Data" });
    }

    // ---------------------------------------------------------------------
    // VPC Endpoints + 공용 SG — 신규 VPC 모드에서만 생성.
    // 기존 VPC 재사용 모드에서는 운영자가 endpoints와 SG를 직접 관리한다.
    // ---------------------------------------------------------------------
    if (!isExistingMode) {
      const endpointSg = new ec2.SecurityGroup(this, "EndpointSg", {
        vpc: this.vpc,
        description: "Shared SG for interface VPC endpoints (443 from VPC CIDR)",
        allowAllOutbound: false,
      });
      endpointSg.addIngressRule(
        ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
        ec2.Port.tcp(443),
        "HTTPS from VPC CIDR",
      );
      this.endpointSecurityGroup = endpointSg;

      // cdk-nag EC23: ingress CIDR이 Fn::GetAtt(Vpc.CidrBlock)을 사용해
      // 정적 분석 불가 → false-positive. VPC 내부 트래픽만 허용하므로 의도된 설정.
      NagSuppressions.addResourceSuppressions(endpointSg, [
        {
          id: "AwsSolutions-EC23",
          reason:
            "Endpoint SG ingress is scoped to the VPC CIDR (intrinsic Fn::GetAtt). cdk-nag static analyzer cannot resolve this but the rule is satisfied.",
        },
      ]);

      const interfaceEndpoints: ReadonlyArray<{
        id: string;
        service: ec2.InterfaceVpcEndpointAwsService;
      }> = [
        { id: "EcrApi", service: ec2.InterfaceVpcEndpointAwsService.ECR },
        { id: "EcrDkr", service: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER },
        { id: "Logs", service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS },
        { id: "Ssm", service: ec2.InterfaceVpcEndpointAwsService.SSM },
        { id: "SsmMessages", service: ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES },
        { id: "Secrets", service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER },
        { id: "Kms", service: ec2.InterfaceVpcEndpointAwsService.KMS },
        { id: "BedrockRuntime", service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME },
      ];

      for (const ep of interfaceEndpoints) {
        this.vpc.addInterfaceEndpoint(ep.id, {
          service: ep.service,
          subnets: this.appSubnets,
          securityGroups: [endpointSg],
          privateDnsEnabled: true,
        });
      }

      // AgentCore endpoint — L2에 미등록 시 L1로 우회.
      new ec2.InterfaceVpcEndpoint(this, "BedrockAgentCore", {
        vpc: this.vpc,
        service: new ec2.InterfaceVpcEndpointService(
          `com.amazonaws.${this.region}.bedrock-agentcore`,
          443,
        ),
        subnets: this.appSubnets,
        securityGroups: [endpointSg],
        privateDnsEnabled: true,
      });

      // S3 Gateway endpoint — 무료, ECR layer pull 시 S3 백엔드 호출에 필수.
      this.vpc.addGatewayEndpoint("S3", {
        service: ec2.GatewayVpcEndpointAwsService.S3,
        subnets: [this.appSubnets, this.dataSubnets],
      });
    }

    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "VpcId", { value: this.vpc.vpcId });
    if (!isExistingMode) {
      new cdk.CfnOutput(this, "AppSubnetIds", {
        value: this.vpc.selectSubnets(this.appSubnets).subnetIds.join(","),
      });
      new cdk.CfnOutput(this, "DataSubnetIds", {
        value: this.vpc.selectSubnets(this.dataSubnets).subnetIds.join(","),
      });
      if (this.endpointSecurityGroup) {
        new cdk.CfnOutput(this, "EndpointSgId", {
          value: this.endpointSecurityGroup.securityGroupId,
        });
      }
    }
  }
}

function parseCsvContext(raw: unknown): string[] {
  if (typeof raw !== "string" || raw.length === 0) {
    return [];
  }
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}
