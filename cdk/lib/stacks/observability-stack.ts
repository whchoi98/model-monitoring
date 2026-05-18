// ObservabilityStack - CloudWatch Alarms + Dashboard + SNS topic.
//
// 로그 그룹은 각 서비스 스택(AppServices, Scheduler)에서 이미 생성하므로 본 스택은
// 알람과 시각화에 집중.
import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cwActions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as sns from "aws-cdk-lib/aws-sns";
import { NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";

export interface ObservabilityStackProps extends cdk.StackProps {
  readonly alb: elbv2.IApplicationLoadBalancer;
  readonly cluster: ecs.ICluster;
  readonly backendService: ecs.IBaseService;
  readonly frontendService: ecs.IBaseService;
  readonly db: rds.IDatabaseInstance;
  /** SNS 알림 받을 이메일 주소 - 미지정 시 SNS topic만 생성, subscribe는 운영자가 콘솔에서. */
  readonly alarmEmail?: string;
}

export class ObservabilityStack extends cdk.Stack {
  public readonly alarmTopic: sns.Topic;
  public readonly dashboard: cloudwatch.Dashboard;

  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // SNS 알림 토픽 - 모든 알람의 destination.
    // ---------------------------------------------------------------------
    this.alarmTopic = new sns.Topic(this, "AlarmTopic", {
      topicName: "bedrock-monitor-alarms",
      displayName: "Bedrock Monitor v2 Alarms",
      enforceSSL: true,
      masterKey: undefined, // 기본 AWS-managed encryption - KMS 키 충돌 방지.
    });

    if (props.alarmEmail) {
      new sns.Subscription(this, "AlarmEmail", {
        topic: this.alarmTopic,
        protocol: sns.SubscriptionProtocol.EMAIL,
        endpoint: props.alarmEmail,
      });
    }

    const alarmAction = new cwActions.SnsAction(this.alarmTopic);

    // ---------------------------------------------------------------------
    // 알람 정의.
    // ---------------------------------------------------------------------
    const alarms: cloudwatch.Alarm[] = [];

    // ALB 5xx 비율 > 1% (5분 윈도우, 2회 연속).
    // IApplicationLoadBalancer는 loadBalancerFullName 미노출 - ConcreteApplicationLoadBalancer로 캐스팅.
const albName = (props.alb as elbv2.ApplicationLoadBalancer).loadBalancerFullName;
    const alb5xxRatio = new cloudwatch.MathExpression({
      expression: "100 * (m5xx / IF(req != 0, req, 1))",
      label: "ALB 5xx Ratio (%)",
      usingMetrics: {
        m5xx: new cloudwatch.Metric({
          namespace: "AWS/ApplicationELB",
          metricName: "HTTPCode_Target_5XX_Count",
          dimensionsMap: { LoadBalancer: albName },
          statistic: "Sum",
          period: cdk.Duration.minutes(5),
        }),
        req: new cloudwatch.Metric({
          namespace: "AWS/ApplicationELB",
          metricName: "RequestCount",
          dimensionsMap: { LoadBalancer: albName },
          statistic: "Sum",
          period: cdk.Duration.minutes(5),
        }),
      },
    });
    const alb5xxAlarm = new cloudwatch.Alarm(this, "Alb5xxRatioAlarm", {
      metric: alb5xxRatio,
      threshold: 1.0,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: "ALB target 5xx > 1% over 2x5min",
    });
    alarms.push(alb5xxAlarm);

    // ALB target 응답시간 p95 > 3s.
    const albLatencyAlarm = new cloudwatch.Alarm(this, "AlbLatencyAlarm", {
      metric: new cloudwatch.Metric({
        namespace: "AWS/ApplicationELB",
        metricName: "TargetResponseTime",
        dimensionsMap: { LoadBalancer: albName },
        statistic: "p95",
        period: cdk.Duration.minutes(5),
      }),
      threshold: 3.0,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: "ALB p95 response time > 3s (5분 윈도우, 2회 연속)",
    });
    alarms.push(albLatencyAlarm);

    // ECS Service running task count < 1 (3분 연속).
    const ecsDownAlarm = (serviceName: string, svc: ecs.IBaseService) =>
      new cloudwatch.Alarm(this, `${serviceName}DownAlarm`, {
        metric: new cloudwatch.Metric({
          namespace: "ECS/ContainerInsights",
          metricName: "RunningTaskCount",
          dimensionsMap: {
            ClusterName: props.cluster.clusterName,
            ServiceName: svc.serviceName,
          },
          statistic: "Average",
          period: cdk.Duration.minutes(1),
        }),
        threshold: 1,
        evaluationPeriods: 3,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.BREACHING,
        alarmDescription: `${serviceName} running task < 1 for 3 minutes`,
      });

    alarms.push(ecsDownAlarm("Backend", props.backendService));
    alarms.push(ecsDownAlarm("Frontend", props.frontendService));

    // RDS CPU > 80% (5분 연속).
    const rdsCpuAlarm = new cloudwatch.Alarm(this, "RdsCpuAlarm", {
      metric: props.db.metricCPUUtilization({ period: cdk.Duration.minutes(5) }),
      threshold: 80,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: "RDS CPUUtilization > 80% for 5 minutes",
    });
    alarms.push(rdsCpuAlarm);

    // RDS FreeStorageSpace < 2GB.
    const rdsStorageAlarm = new cloudwatch.Alarm(this, "RdsStorageAlarm", {
      metric: props.db.metricFreeStorageSpace({ period: cdk.Duration.minutes(5) }),
      threshold: 2 * 1024 * 1024 * 1024, // 2 GiB in bytes
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: "RDS free storage < 2 GiB",
    });
    alarms.push(rdsStorageAlarm);

    // RDS DB 연결 수 > 80 (t4g.micro 기본 max_connections 약 80~85).
    const rdsConnAlarm = new cloudwatch.Alarm(this, "RdsConnectionsAlarm", {
      metric: props.db.metricDatabaseConnections({ period: cdk.Duration.minutes(5) }),
      threshold: 80,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: "RDS DatabaseConnections > 80 (near max for t4g.micro)",
    });
    alarms.push(rdsConnAlarm);

    // 모든 알람 → SNS.
    for (const alarm of alarms) {
      alarm.addAlarmAction(alarmAction);
      alarm.addOkAction(alarmAction);
    }

    // ---------------------------------------------------------------------
    // CloudWatch Dashboard.
    // ---------------------------------------------------------------------
    this.dashboard = new cloudwatch.Dashboard(this, "Dashboard", {
      dashboardName: "BedrockMonitor-v2",
      defaultInterval: cdk.Duration.hours(3),
    });

    const albMetric = (name: string, stat = "Sum") =>
      new cloudwatch.Metric({
        namespace: "AWS/ApplicationELB",
        metricName: name,
        dimensionsMap: { LoadBalancer: albName },
        statistic: stat,
        period: cdk.Duration.minutes(5),
      });

    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "ALB Requests / 5xx",
        width: 12,
        left: [albMetric("RequestCount")],
        right: [albMetric("HTTPCode_Target_5XX_Count")],
      }),
      new cloudwatch.GraphWidget({
        title: "ALB Target Response Time (p50/p95)",
        width: 12,
        left: [albMetric("TargetResponseTime", "p50"), albMetric("TargetResponseTime", "p95")],
      }),
    );

    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "ECS Running Tasks (backend / frontend)",
        width: 12,
        left: [
          new cloudwatch.Metric({
            namespace: "ECS/ContainerInsights",
            metricName: "RunningTaskCount",
            dimensionsMap: {
              ClusterName: props.cluster.clusterName,
              ServiceName: props.backendService.serviceName,
            },
            statistic: "Average",
            period: cdk.Duration.minutes(1),
            label: "backend",
          }),
          new cloudwatch.Metric({
            namespace: "ECS/ContainerInsights",
            metricName: "RunningTaskCount",
            dimensionsMap: {
              ClusterName: props.cluster.clusterName,
              ServiceName: props.frontendService.serviceName,
            },
            statistic: "Average",
            period: cdk.Duration.minutes(1),
            label: "frontend",
          }),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: "RDS CPU / FreeStorage",
        width: 12,
        left: [props.db.metricCPUUtilization()],
        right: [props.db.metricFreeStorageSpace()],
      }),
    );

    this.dashboard.addWidgets(
      new cloudwatch.AlarmStatusWidget({
        title: "All Alarms",
        alarms,
        width: 24,
      }),
    );

    // ---------------------------------------------------------------------
    // cdk-nag suppressions.
    // ---------------------------------------------------------------------
    NagSuppressions.addResourceSuppressions(this.alarmTopic, [
      {
        id: "AwsSolutions-SNS2",
        reason:
          "Default AWS-managed encryption is acceptable for alarm topic - alarms contain operational metadata, not customer data.",
      },
    ]);

    // ---------------------------------------------------------------------
    // Outputs.
    // ---------------------------------------------------------------------
    new cdk.CfnOutput(this, "AlarmTopicArn", { value: this.alarmTopic.topicArn });
    new cdk.CfnOutput(this, "DashboardUrl", {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${this.dashboard.dashboardName}`,
    });
    new cdk.CfnOutput(this, "AlarmCount", { value: String(alarms.length) });
  }
}
