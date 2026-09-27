# Pricing

> For the complete documentation index, see [llms.txt](/llms.txt). Markdown versions of documentation pages are available by appending `.md` to the page URL.

FedRAMP endpoints are charged a 10% uplift over the corresponding standard model
rates.
<a id="astra"></a>
<a id="latest-models"></a>


  

    

Flagship models


    
Our latest models

    
Prices per 1M tokens.

  

  

Standard


      
### Standard pricing data

| Model | Short context input | Short context cached input | Short context cache writes | Short context output | Long context input | Long context cached input | Long context cache writes | Long context output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6-astra | $10.00 | $1.00 | $12.50 | $50.00 | $20.00 | $2.00 | $25.00 | $75.00 |
| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |
| gpt-6-luna | $0.10 | $0.01 | $0.125 | $0.50 | $0.20 | $0.02 | $0.25 | $0.75 |
| gpt-5.6-sol | $4.00 | $0.40 | $5.00 | $20.00 | $8.00 | $0.80 | $10.00 | $30.00 |
| gpt-5.6-terra | $2.00 | $0.20 | $2.50 | $12.00 | $4.00 | $0.40 | $5.00 | $18.00 |
| gpt-5.6-luna | $0.20 | $0.02 | $0.25 | $1.20 | $0.40 | $0.04 | $0.50 | $1.80 |
| gpt-5.5 (<272K context length) | $5.00 | $0.50 | - | $30.00 | $10.00 | $1.00 | - | $45.00 |
| gpt-5.5-pro (<272K context length) | $30.00 | - | - | $180.00 | $60.00 | - | - | $270.00 |
| gpt-5.4 (<272K context length) | $2.50 | $0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |
| gpt-5.4-mini | $0.75 | $0.075 | - | $4.50 | - | - | - | - |
| gpt-5.4-nano | $0.20 | $0.02 | - | $1.25 | - | - | - | - |
| gpt-5.4-pro (<272K context length) | $30.00 | - | - | $180.00 | $60.00 | - | - | $270.00 |
| gpt-5.2 | $1.75 | $0.175 | - | $14.00 | - | - | - | - |
| gpt-5.2-pro | $21.00 | - | - | $168.00 | - | - | - | - |
| gpt-5.1 | $1.25 | $0.125 | - | $10.00 | - | - | - | - |
| gpt-5 | $1.25 | $0.125 | - | $10.00 | - | - | - | - |
| gpt-5-mini | $0.25 | $0.025 | - | $2.00 | - | - | - | - |
| gpt-5-nano | $0.05 | $0.005 | - | $0.40 | - | - | - | - |
| gpt-5-pro | $15.00 | - | - | $120.00 | - | - | - | - |
| gpt-4.1 | $2.00 | $0.50 | - | $8.00 | - | - | - | - |
| gpt-4.1-mini | $0.40 | $0.10 | - | $1.60 | - | - | - | - |
| gpt-4.1-nano | $0.10 | $0.025 | - | $0.40 | - | - | - | - |
| gpt-4o | $2.50 | $1.25 | - | $10.00 | - | - | - | - |
| gpt-4o-2024-05-13 | $5.00 | - | - | $15.00 | - | - | - | - |
| gpt-4o-mini | $0.15 | $0.075 | - | $0.60 | - | - | - | - |
| o1 | $15.00 | $7.50 | - | $60.00 | - | - | - | - |
| o1-pro | $150.00 | - | - | $600.00 | - | - | - | - |
| o3-pro | $20.00 | - | - | $80.00 | - | - | - | - |
| o3 | $2.00 | $0.50 | - | $8.00 | - | - | - | - |
| o4-mini | $1.10 | $0.275 | - | $4.40 | - | - | - | - |
| o3-mini | $1.10 | $0.55 | - | $4.40 | - | - | - | - |
| gpt-4-turbo-2024-04-09 | $10.00 | - | - | $30.00 | - | - | - | - |
| gpt-4-0613 | $30.00 | - | - | $60.00 | - | - | - | - |
| gpt-3.5-turbo | $0.50 | - | - | $1.50 | - | - | - | - |
| gpt-3.5-turbo-0125 | $0.50 | - | - | $1.50 | - | - | - | - |
| gpt-3.5-turbo-1106 | $1.00 | - | - | $2.00 | - | - | - | - |
| gpt-3.5-turbo-instruct | $1.50 | - | - | $2.00 | - | - | - | - |
| davinci-002 | $2.00 | - | - | $2.00 | - | - | - | - |
| babbage-002 | $0.40 | - | - | $0.40 | - | - | - | - |

Regional processing (data residency) endpoints are charged a 10% uplift for models released on or after March 5, 2026, that are eligible for data residency. For GPT-6 Sol and Luna, EU data residency is available only with Standard processing. See our [Your data](https://developers.openai.com/api/docs/guides/your-data) guide for supported regions and processing details. [OpenAI models in Amazon Bedrock](https://developers.openai.com/api/docs/guides/amazon-bedrock) are billed through AWS. Bedrock pricing in commercial regions matches OpenAI direct pricing for equivalent services. Priority processing was renamed Fast mode on July 30, 2026. You can use either `service_tier: "priority"` or `service_tier: "fast"` in your API requests. [Learn more about Fast mode](https://developers.openai.com/api/docs/guides/fast-mode). GPT-5.6 Sol’s promotional pricing is available at least through November 21, 2026.

    

    

      
Batch


      
### Batch pricing data

| Model | Short context input | Short context cached input | Short context cache writes | Short context output | Long context input | Long context cached input | Long context cache writes | Long context output |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6-astra | $5.00 | $0.50 | $6.25 | $25.00 | $10.00 | $1.00 | $12.50 | $37.50 |
| gpt-6-sol | $1.00 | $0.10 | $1.25 | $5.00 | $2.00 | $0.20 | $2.50 | $7.50 |
| gpt-6-luna | $0.05 | $0.005 | $0.0625 | $0.25 | $0.10 | $0.01 | $0.125 | $0.375 |
| gpt-5.6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $4.00 | $0.40 | $5.00 | $15.00 |
| gpt-5.6-terra | $1.00 | $0.10 | $1.25 | $6.00 | $2.00 | $0.20 | $2.50 | $9.00 |
| gpt-5.6-luna | $0.10 | $0.01 | $0.125 | $0.60 | $0.20 | $0.02 | $0.25 | $0.90 |
| gpt-5.5 (<272K context length) | $2.50 | $0.25 | - | $15.00 | $5.00 | $0.50 | - | $22.50 |
| gpt-5.5-pro (<272K context length) | $15.00 | - | - | $90.00 | - | - | - | - |
| gpt-5.4 (<272K context length) | $1.25 | $0.13 | - | $7.50 | $2.50 | $0.25 | - | $11.25 |
| gpt-5.4-mini | $0.375 | $0.0375 | - | $2.25 | - | - | - | - |
| gpt-5.4-nano | $0.10 | $0.01 | - | $0.625 | - | - | - | - |
| gpt-5.4-pro (<272K context length) | $15.00 | - | - | $90.00 | $30.00 | - | - | $135.00 |
| gpt-5.2 | $0.875 | $0.0875 | - | $7.00 | - | - | - | - |
| gpt-5.2-pro | $10.50 | - | - | $84.00 | - | - | - | - |
| gpt-5.1 | $0.625 | $0.0625 | - | $5.00 | - | - | - | - |
| gpt-5 | $0.625 | $0.0625 | - | $5.00 | - | - | - | - |
| gpt-5-mini | $0.125 | $0.0125 | - | $1.00 | - | - | - | - |
| gpt-5-nano | $0.025 | $0.0025 | - | $0.20 | - | - | - | - |
| gpt-5-pro | $7.50 | - | - | $60.00 | - | - | - | - |
| gpt-4.1 | $1.00 | - | - | $4.00 | - | - | - | - |
| gpt-4.1-mini | $0.20 | - | - | $0.80 | - | - | - | - |
| gpt-4.1-nano | $0.05 | - | - | $0.20 | - | - | - | - |
| gpt-4o | $1.25 | - | - | $5.00 | - | - | - | - |
| gpt-4o-2024-05-13 | $2.50 | - | - | $7.50 | - | - | - | - |
| gpt-4o-mini | $0.075 | - | - | $0.30 | - | - | - | - |
| o1 | $7.50 | - | - | $30.00 | - | - | - | - |
| o1-pro | $75.00 | - | - | $300.00 | - | - | - | - |
| o3-pro | $10.00 | - | - | $40.00 | - | - | - | - |
| o3 | $1.00 | - | - | $4.00 | - | - | - | - |
| o4-mini | $0.55 | - | - | $2.20 | - | - | - | - |
| o3-mini | $0.55 | - | - | $2.20 | - | - | - | - |
| gpt-4-turbo-2024-04-09 | $5.00 | - | - | $15.00 | - | - | - | - |
| gpt-4-0613 | $15.00 | - | - | $30.00 | - | - | - | - |
| gpt-3.5-turbo-0125 | $0.25 | - | - | $0.75 | - | - | - | - |
| gpt-3.5-turbo-1106 | $1.00 | - | - | $2.00 | - | - | - | - |
| davinci-002 | $1.00 | - | - | $1.00 | - | - | - | - |
| babbage-002 | $0.20 | - | - | $0.20 | - | - | - | - |

For GPT-6 Sol and Luna, EU data residency is available only with Standard processing. Regional processing (data residency) endpoints are charged a 10% uplift for models released on or after March 5, 2026, that are eligible for data residency. See our [Your data](https://developers.openai.com/api/docs/guides/your-data) guide for supported regions and processing details.

    

    

      
Flex


      
