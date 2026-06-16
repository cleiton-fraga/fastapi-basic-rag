"""
Esquemas Pydantic para endpoints de RAG: upload de documentos e perguntas/respostas.

- Define payloads de requisição e resposta usados pelas rotas de RAG.
- Não utiliza variáveis de ambiente.
"""

from pydantic import BaseModel, Field
from typing import List

class UploadDocRequest(BaseModel):
    title: str = Field(description="Título do documento")
    content: str = Field(description="Conteúdo do documento em texto")

class UploadDocResponse(BaseModel):
    doc_id: str = Field(description="Identificador do documento gerado")
    chunks: int = Field(description="Quantidade de chunks criados")

class AskRequest(BaseModel):
    doc_id: str = Field(description="Documento alvo da busca")
    question: str = Field(description="Pergunta do usuário")
    k: int = Field(default=5, description="Quantidade de chunks finais usados no contexto (após rerank)")
    candidates: int = Field(default=30, description="Quantidade de candidatos recuperados na busca híbrida antes do rerank")

class AnswerResponse(BaseModel):
    answer: str = Field(description="Resposta gerada pelo modelo")
    sources: List[str] = Field(description="Referências dos chunks usados")