"""
Middleware da camada de guardrails — o envelope transparente que envolve o núcleo.

Tratar a segurança como middleware permite interceptar a requisição sem reescrever
os endpoints. Este middleware (ASGI puro) cuida da parte transversal:

- atribui um `request_id` (correlação) acessível via `request.state.request_id` e
  devolvido no header `X-Request-ID` — é a chave que costura a trilha de auditoria
  das rails;
- mede a latência fim-a-fim e a expõe em `X-Process-Time`.

A **aplicação** das rails (input antes do LLM, output depois) vive dentro do
handler `/rag/ask`. Essa é uma decisão deliberada: o output rail de fidelidade
precisa dos trechos recuperados (o contexto), que só existem no meio do fluxo do
endpoint — algo a que um middleware puro não tem acesso. O middleware fornece o
envelope/correlação; as rails fazem a interceptação de conteúdo onde o contexto
está disponível.

Os símbolos da Starlette são importados de forma preguiçosa (dentro de `__call__`):
o núcleo das rails (`app.guardrails.rails` e detectores) fica importável sem o
framework web, mantendo a lógica de segurança desacoplada e testável isoladamente.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable
from uuid import uuid4

Scope = dict
Message = dict
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class GuardrailsMiddleware:
    """Envelope de correlação e latência para a camada de segurança."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import MutableHeaders  # import preguiçoso

        request_id = str(uuid4())
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        start = time.perf_counter()

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Process-Time"] = f"{(time.perf_counter() - start) * 1000:.1f}ms"
            await send(message)

        await self.app(scope, receive, send_with_headers)
