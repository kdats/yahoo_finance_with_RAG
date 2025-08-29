# app.py
import streamlit as st
from rag_answers import answer

st.set_page_config(page_title="Financials RAG (Vertex AI)")
st.title("Financials RAG (Vertex AI)")

q = st.text_input("Ask a financial question (e.g., 'Compare operating income of Tesla across the last three years.')")
if st.button("Ask") and q.strip():
    out = answer(q)   # This should call your Gemini/Vertex AI function
    st.write(out)
