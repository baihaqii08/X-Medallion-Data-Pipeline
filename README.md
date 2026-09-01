# Automated Medallion Data Pipeline (X/Twitter to MinIO)

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Playwright](https://img.shields.io/badge/Playwright-Web_Scraping-green)
![Beanstalkd](https://img.shields.io/badge/Beanstalkd-Message_Queue-orange)
![MinIO](https://img.shields.io/badge/MinIO-S3_Data_Lake-red)

A data engineering pipeline designed to intercept X (Twitter) GraphQL payloads and orchestrate data flow into a MinIO object storage backend utilizing a Medallion architecture. The system relies on asynchronous message queues for decoupling and implements deterministic object keys for idempotent upserts.

## Architecture

```mermaid
flowchart LR
    %% Minimalist Corporate Styling
    classDef extract fill:#ffffff,stroke:#333333,stroke-width:1px,color:#000000,rx:2px,ry:2px
    classDef storage fill:#f9f9f9,stroke:#666666,stroke-width:1px,color:#000000,rx:5px,ry:5px
    classDef queue fill:#eeeeee,stroke:#666666,stroke-width:1px,color:#000000,rx:10px,ry:10px
    classDef ext fill:#ffffff,stroke:#000000,stroke-width:2px,color:#000000,rx:20px,ry:20px
    classDef control fill:#ffffff,stroke:#000000,stroke-width:1px,stroke-dasharray: 5 5,color:#000000

    %% Components
    API(((X GraphQL API))):::ext
    Cron{auto_pipeline.py}:::control

    subgraph Extraction Layer
        Interceptor["twitter_batch_interceptor.py<br/>(Playwright)"]:::extract
    end

    subgraph Bronze Layer
        RawJSON[("Local JSON<br/>raw_batches/")]:::storage
        Parser["twitter_parser.py<br/>(Normalizer)"]:::extract
        GZIP[("Archive<br/>.json.gz")]:::storage
    end

    subgraph Silver Layer
        Beanstalkd(["Beanstalkd<br/>(Queue)"]):::queue
        Worker["minio_worker.py<br/>(Boto3 / Upsert)"]:::extract
        MinIO[("MinIO S3")]:::storage
    end

    %% Flow
    Cron -.->|Trigger| Interceptor
    Cron -.->|Trigger| Parser
    API == Network Intercept ==> Interceptor
    Interceptor -->|JSON Dump| RawJSON
    RawJSON -->|Read| Parser
    Parser -->|Compress| GZIP
    Parser -->|Publish| Beanstalkd
    Beanstalkd -->|Consume| Worker
    Worker == PutObject ==> MinIO
```

## Features
- **GraphQL Interception:** Utilizes Playwright to capture raw network responses, bypassing DOM traversal.
- **Message Queue Decoupling:** Employs Beanstalkd to separate extraction workloads from I/O bound loading operations.
- **Idempotency:** Implements deterministic S3 object key generation (`post_id`) to ensure upsert behavior and prevent data duplication.
- **Storage Optimization:** Applies GZIP compression on raw Bronze layer JSON payloads.
- **Validation Pipeline:** Integrates a regex-based validation module to filter out NSFW and predefined negative keywords before entering the Silver layer.

## System Requirements
- Python 3.11+
- Beanstalkd daemon
- MinIO instance (or AWS S3 credentials)

## Local Setup

1. Clone the repository and configure the virtual environment:
   ```bash
   python -m venv .venv
   source .venv/Scripts/activate
   pip install -r requirements.txt
   playwright install chromium
   ```
2. Configure environment variables:
   ```bash
   cp .env.example .env
   ```
   Provide valid Twitter authentication cookies (`TWITTER_AUTH_TOKEN`, `TWITTER_CT0`) and S3 endpoint credentials in the `.env` file.
   
3. Execute the worker process (Terminal 1):
   ```bash
   python minio_worker.py
   ```
   
4. Execute the pipeline scheduler (Terminal 2):
   ```bash
   python auto_pipeline.py
   ```
