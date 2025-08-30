# Architecture Design Diagram

<img width="1547" height="1460" alt="image" src="https://github.com/user-attachments/assets/48404d3c-f0db-41ef-9a1a-e3afd23a928c" />
# Explaination
* A Python wrapper file leverages the yfinance library to pull annual income statements and balance sheets, normalizing required metrics like revenue, net income and cash equivalents for each ticker-year pair

* The pipeline writes per‑record JSON files and consolidates all normalized records into bulk JSONL and CSV outputs for later stages After data extraction, the `financials.jsonl` file is uploaded to Google Cloud Storage to stage data for the cloud pipeline, as shown in the architecture diagram

* `BigQuery` ingests the staged JSONL into a raw table financials_raw, forming the foundation for downstream processing. A derived BigQuery table financials_text concatenates ticker, fiscal year and key fields into a single doc_text string while preserving the original JSON row

* An embeddings table financials_vect with an ARRAY<FLOAT64> column is created to hold vector representations for vector search

* Vertex AI’s `text-embedding-004` model generates embeddings for each doc_text and writes them into financials_vect via BigQuery’s load API

* User questions are embedded with the same model, and BigQuery’s `COSINE_DISTANCE` operator retrieves the `top‑k` closest financial records from financials_vect

* Retrieved snippets are assembled into a prompt and sent to the Gemini generative model, which produces the grounded answer returned to the user

* A Streamlit front‑end calls this RAG answer function, letting users pose financial questions interactively

* The application is to be containerized and deployed using Cloud Build to Cloud Run for managed, scalable hosting. IAM service accounts enforce least‑privilege access, and Cloud Monitoring/Logging provide observability across the deployed stack
  
# Data Acquisition Approach

We iteratively explored multiple methods for acquiring public company financial data:

1. **Web Scraping with BeautifulSoup (bs4):**

   * Initial attempts involved scraping financial tables from websites like Yahoo Finance and MacroTrends using `requests` and `BeautifulSoup4`.
   * We encountered challenges due to dynamic content, bot-blocking, and inconsistent HTML structure.

2. **LangChain Automation:**

   * Next, we experimented with [LangChain](https://python.langchain.com/) for orchestrated scraping flowsto automate browser-based extraction for JavaScript-rendered tables.
   * This approach worked for some static snapshots but proved fragile, slow, and less scalable for batch ingestion.

3. **Programmatic APIs and `yfinance`:**

   * We explored public APIs (e.g., Yahoo Finance’s unofficial endpoints, SEC’s EDGAR XBRL “companyfacts”), but these often required complex field mapping and additional API management. Below are the companies we targeted with a period range.
  
| Company   | Ticker | Years      |
| --------- | ------ | ---------- |
| Apple     | AAPL   | 2021–2024  |
| Amazon    | AMZN   | 2021–2024  |
| Alphabet  | GOOGL  | 2021–2024  |
| Microsoft | MSFT   | 2022–2024  |
| Tesla     | TSLA   | 2021–2024  |

   * Finally, we standardized on the open-source `yfinance` Python library, which reliably fetches annual **Income Statement** and **Balance Sheet** data for major tickers directly from Yahoo Finance.
   * This let us robustly extract all assignment-mandated fields (revenue, gross profit, net income, EPS, assets, liabilities, equity, and cash & cash equivalents) and normalize them into JSONL, CSV, and per-record JSON for downstream RAG.

# GCP Services Used (and Their Roles)

Below is the full list of **GCP services used in the production pipeline**, and what each is responsible for:

| GCP Service                            | Role in Pipeline                                                                                                                                                  |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Google Cloud Storage**               | Stores normalized datasets (`financials.jsonl`, CSV) uploaded from local after scraping.                                                                          |
| **BigQuery**                           | Data warehouse: ingests raw JSONL as `financials_raw`, produces `financials_text` (for embeddings), and hosts `financials_vect` with vector search for retrieval. |
| **Vertex AI Embeddings**               | Generates text embeddings for each financials record (model: `text-embedding-004`).                                                                               |
| **Vertex AI Gemini Pro**               | Large Language Model for answer generation (retrieval-augmented), using grounded context.                                                                         |
| **Cloud Run**                          | Deploys the Streamlit app for web-based user interface.                                                                                                           |

| GCP Service to be used for deployment  | Role in Pipeline   
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Cloud Build**                        | CI/CD: Builds and deploys Docker images for Cloud Run, and can schedule scraping jobs.                                                                            |
| **IAM (Identity & Access Management)** | Manages service account permissions for secure, least-privilege access to all components.                                                                         |
| **Cloud Monitoring/Logging**           | Collects logs and metrics for the deployed application and RAG pipeline for monitoring and troubleshooting.                                                       |


# Setup instructions.
## Runbook — Execute Full GCP Deployment (commands you can run locally)

> **Before we start**: following placeholders should be replaced with the approprite values:
> - `PROJECT_ID` — your GCP project id (e.g. `gen-lang-client-0981824891`)
> - `BUCKET` — your Cloud Storage bucket (e.g. `resolvetech_bucket`)
> - `REGION` — region (e.g. `us-central1`)


## 0) Local prerequisites (run in VS Code terminal inside your venv)

1. Open VS Code terminal (PowerShell) and activate your venv.
2. Install Python deps used by scripts:

```powershell
pip install --upgrade pip
pip install yfinance pandas numpy pyarrow google-cloud-bigquery google-cloud-aiplatform vertexai streamlit db-types
pip install --upgrade google-cloud-aiplatform
```

## 1) Install Google Cloud SDK (gcloud, gsutil, bq)

1. Download & install from: https://cloud.google.com/sdk/docs/install
2. Restart terminal.
3. Verify:

```powershell
gcloud --version
gsutil --version
bq --version
```

---

## 2) Authenticate & set project

Run in **PowerShell or CMD** (either):

```powershell
# Set variables
$PROJECT_ID=your-project-id
$REGION=us-central1
$BUCKET=resolvetech_bucket

# Authenticate interactive browser login (use account with billing)
gcloud auth login

gcloud config set project $PROJECT_ID

gcloud config set compute/region $REGION

# Application Default Credentials for Python libs
gcloud auth application-default login
```
---
## 3) Create GCS bucket (if you don't have one)

```powershell
# Create bucket (global unique name)
gsutil mb -p $PROJECT_ID -l $REGION gs://$BUCKET
```

---

## 4) Run the scraper locally and upload data to GCS

1. Run the yfinance scraper (local). Example (adjust script name if different):

```powershell
python yfinance_financials_pipeline.py --tickers TSLA AAPL MSFT GOOGL AMZN --years 2021 2022 2023 2024 --out ./data
```

2. Confirm files exist:

```powershell
ls .\data\normalized\financials.jsonl
ls .\data\normalized\*.json
```

3. Upload JSONL to GCS:

```powershell
gsutil cp .\data\normalized\financials.jsonl gs://$BUCKET/financials/financials.jsonl
```

---

## 5) BigQuery: create dataset and load raw JSONL

1. Create dataset (run in PowerShell or CMD):

```powershell
bq --location=US mk --dataset $PROJECT_ID:rag_fin
```

2. Load JSONL using autodetect (fast):

```powershell
bq load --autodetect --source_format=NEWLINE_DELIMITED_JSON rag_fin.financials_raw gs://$BUCKET/financials/financials.jsonl
```

3. Verify table exists:

```powershell
bq ls rag_fin
bq show --format=prettyjson $PROJECT_ID:rag_fin.financials_raw
```

---

## 6) Build `financials_text` table (one-liner)

**PowerShell (use single quotes around the SQL):**

```powershell
bq query --use_legacy_sql=false 'CREATE OR REPLACE TABLE `'"$PROJECT_ID"'.rag_fin.financials_text` AS SELECT ticker, fiscal_year, CONCAT("Ticker: ", ticker, "\n","Fiscal Year: ", CAST(fiscal_year AS STRING), "\n","Revenue: ", CAST(income_statement.revenue AS STRING), "\n","Gross Profit: ", CAST(income_statement.gross_profit AS STRING), "\n","Operating Income: ", CAST(income_statement.operating_income AS STRING), "\n","Net Income: ", CAST(income_statement.net_income AS STRING), "\n","EPS (diluted): ", CAST(income_statement.eps_diluted AS STRING), "\n","Assets: ", CAST(balance_sheet.assets AS STRING), "\n","Liabilities: ", CAST(balance_sheet.liabilities AS STRING), "\n","Equity: ", CAST(balance_sheet.equity AS STRING), "\n","Cash & Cash Equivalents: ", CAST(balance_sheet.cash_and_cash_equivalents AS STRING)) AS doc_text, TO_JSON_STRING(t) AS json_row FROM `'"$PROJECT_ID"'.rag_fin.financials_raw` t'
```

**CMD (single command, double quotes around SQL):**

```cmd
bq query --use_legacy_sql=false "CREATE OR REPLACE TABLE `" + %PROJECT_ID% + ".rag_fin.financials_text` AS SELECT ticker, fiscal_year, CONCAT('Ticker: ', ticker, '
','Fiscal Year: ', CAST(fiscal_year AS STRING), '
','Revenue: ', CAST(income_statement.revenue AS STRING), '
','Gross Profit: ', CAST(income_statement.gross_profit AS STRING), '
','Operating Income: ', CAST(income_statement.operating_income AS STRING), '
','Net Income: ', CAST(income_statement.net_income AS STRING), '
','EPS (diluted): ', CAST(income_statement.eps_diluted AS STRING), '
','Assets: ', CAST(balance_sheet.assets AS STRING), '
','Liabilities: ', CAST(balance_sheet.liabilities AS STRING), '
','Equity: ', CAST(balance_sheet.equity AS STRING), '
','Cash & Cash Equivalents: ', CAST(balance_sheet.cash_and_cash_equivalents AS STRING)) AS doc_text, TO_JSON_STRING(t) AS json_row FROM `" + %PROJECT_ID% + ".rag_fin.financials_raw` t"
```

> If CMD expression is awkward, use the BigQuery web console and paste the multi-line SQL there.

Verify:

```powershell
bq head -n 5 rag_fin.financials_text
```

---

## 7) Create embeddings table `financials_vect`

One-liner to create the empty table with an embedding array column:

```powershell
bq query --use_legacy_sql=false "CREATE OR REPLACE TABLE `$PROJECT_ID.rag_fin.financials_vect` (ticker STRING, fiscal_year INT64, doc_text STRING, json_row STRING, embedding ARRAY<FLOAT64>)"
```

Verify:

```powershell
bq show rag_fin.financials_vect
```

---

## 8) Produce embeddings and populate `financials_vect`

1. Ensure ADC is active for Python clients:

```powershell
gcloud auth application-default login
```

2. Edit `embed_financials.py` to set `PROJECT` and `LOCATION` variables.

3. Run embedding script (this will call Vertex AI embedding model and load results to BigQuery):

```powershell
python embed_financials.py
```

4. Confirm rows:

```powershell
bq head -n 5 rag_fin.financials_vect
```


---

## 9) Test vector retrieval manually (BigQuery example)

1. Create a small test query embedding in Python (example saved to a JSON or variable). You can run quick local Python to print an example embedding vector for a sample question.

2. Use BigQuery to find nearest docs (example placeholder; replace `[...]` with your embedding array):

```sql
DECLARE qvec ARRAY<FLOAT64> = [0.001, 0.002, ...];
SELECT ticker, fiscal_year, doc_text, COSINE_DISTANCE(embedding, qvec) AS dist
FROM `PROJECT_ID.rag_fin.financials_vect`
ORDER BY dist ASC
LIMIT 5;
```

Run via `bq query` or BigQuery console (replace `PROJECT_ID`).

---

## 10) RAG — call Gemini to answer

1. Ensure `vertexai` + `google-cloud-aiplatform` installed in venv.
2. Edit `rag_answer.py` to set `PROJECT` and `LOCATION`.
3. Test locally:

```powershell
python rag_answer.py
```

This script will:
- compute query embedding (TextEmbeddingModel.from_pretrained)
- query BigQuery with the array parameter
- build prompt and call `GenerativeModel('gemini-1.5-pro').generate_content()`

---

## 11) Streamlit local test

```powershell
pip install streamlit
streamlit run app_stl.py
```

Open http://localhost:8501 and test queries.

---

## 12) Containerize & Deploy Streamlit to Cloud Run (prod)

1. Create `Dockerfile` (example provided in your doc). Then build & push:

```powershell
gcloud builds submit --tag gcr.io/$PROJECT_ID/financials-rag:latest
```

2. Deploy to Cloud Run:

```powershell
gcloud run deploy financials-rag --image gcr.io/$PROJECT_ID/financials-rag:latest --region $REGION --platform managed --allow-unauthenticated --memory=1Gi
```

Set IAM/Workload Identity per doc for least privileges.

---

## 13) Clean-up hints

- To delete dataset (careful):

```powershell
bq rm -r -f rag_fin
```

- To delete bucket:

```powershell
gsutil rm -r gs://$BUCKET
```

---
# Sample Results with Screenshots
<img width="1366" height="589" alt="image" src="https://github.com/user-attachments/assets/d9912d26-88db-4dac-9965-339118c35b05" />
<img width="1522" height="646" alt="image" src="https://github.com/user-attachments/assets/5d121b86-f0e6-4d73-8fa5-71c4760ffced" />
<img width="1736" height="659" alt="image" src="https://github.com/user-attachments/assets/26e225b1-42cd-4f91-8ab7-dcefe0c7691c" />
<img width="1433" height="916" alt="image" src="https://github.com/user-attachments/assets/b9d1bcc8-3903-4793-a4e0-a1e570e43ede" />

--- 
# Scope of improvement

* Balanced Retrieval with MMR: Incorporate Maximal Marginal Relevance (MMR) to diversify results, reducing redundancy and providing a broader set of relevant sources per query.

* Hybrid Search Strategies: Combine semantic search with keyword filters, structured metadata, or numeric constraints to retrieve more precise financial context.

* Domain-Specific Embeddings: Explore finance-oriented or multilingual embedding models, enabling richer representations of company filings, news, and global market data.

* Agent-Orchestrated Fetching: Introduce an AI agent to dynamically acquire data, schedule scrapes, validate data quality, and adapt to new sources or failures.

* Conversation Memory & Feedback: Add a conversational agent in the Streamlit app that remembers prior questions, surfaces reasoning paths, and learns from user feedback to refine future responses.
