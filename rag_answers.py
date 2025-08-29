from google.cloud import bigquery
from vertexai.language_models import TextEmbeddingModel
from vertexai.generative_models import GenerativeModel

PROJECT = "gen-lang-client-0981824891"
LOCATION = "us-central1"
DATASET = "rag_fin"
TABLE   = "financials_vect"

def get_query_embedding(q: str):
    model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    emb = model.get_embeddings([q])
    return emb[0].values

def retrieve(q: str, topk=5):
    bq = bigquery.Client(project=PROJECT)
    qvec = get_query_embedding(q)
    sql = f"""
        SELECT ticker, fiscal_year, doc_text, json_row,
               COSINE_DISTANCE(embedding, @qvec) AS dist
        FROM `{PROJECT}.{DATASET}.{TABLE}`
        ORDER BY dist ASC
        LIMIT {topk}
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("qvec", "FLOAT64", qvec)]
    )
    return list(bq.query(sql, job_config=job_config).result())

def answer(q: str):
    ctx = retrieve(q, topk=5)
    context_blob = "\n\n---\n\n".join([row["doc_text"] for row in ctx])

    prompt = f"""You are a financial analyst. Use ONLY the context to answer.
Context:
{context_blob}

Question: {q}
Answer with numbers and cite ticker & fiscal year where relevant."""

    model = GenerativeModel("gemini-2.5-pro")
    resp = model.generate_content(prompt)
    return resp.text

if __name__ == "__main__":
    print(answer("What was Tesla’s net income in 2022 compared to 2021?"))
