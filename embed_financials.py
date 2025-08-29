# embed_financials.py
from google.cloud import aiplatform
from google.cloud import bigquery
from vertexai.language_models import TextEmbeddingModel
import pandas as pd

# ---- CONFIG ----
PROJECT = "gen-lang-client-0981824891"        # <-- fill with your actual project id
LOCATION = "us-central1"
DATASET = "rag_fin"
TABLE   = "financials_text"
EMB_TABLE = "financials_vect"

EMBED_MODEL = "text-embedding-004"  # Vertex AI latest embedding model

# ---- FUNCTIONS ----
def embed_batch(texts, model):
    """Return list of embedding vectors for list of strings."""
    resp = model.get_embeddings(texts)
    # resp is a list of Embedding objects; extract .values
    return [r.values for r in resp]

def main():
    # Init Vertex AI
    aiplatform.init(project=PROJECT, location=LOCATION)
    emb_model = TextEmbeddingModel.from_pretrained(EMBED_MODEL)

    # Fetch source docs from BigQuery
    bq = bigquery.Client(project=PROJECT)
    sql = f"""
        SELECT
          ticker, fiscal_year, doc_text, TO_JSON_STRING(json_row) AS json_str
        FROM `{PROJECT}.{DATASET}.{TABLE}`
    """
    df = bq.query(sql).to_dataframe()

    # Chunking: keep it simple for small dataset
    vecs = embed_batch(df['doc_text'].tolist(), emb_model)

    out = pd.DataFrame({
        "ticker": df["ticker"],
        "fiscal_year": df["fiscal_year"],
        "doc_text": df["doc_text"],
        "json_row": df["json_str"],
        "embedding": vecs,   # each is list<float>
    })

    # BigQuery load job
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",  # overwrite table if rerun
    )
    job = bq.load_table_from_dataframe(
        out,
        f"{PROJECT}.{DATASET}.{EMB_TABLE}",
        job_config=job_config
    )
    job.result()
    print(f"Embeddings written to {PROJECT}.{DATASET}.{EMB_TABLE}")

if __name__ == "__main__":
    main()
# embed_financials.py