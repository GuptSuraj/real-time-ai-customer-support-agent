import math
from google import genai
from google.genai import types
from ..models import EMBEDDING_DIMENSIONS


class EmbeddingUnavailable(RuntimeError):
    pass


def normalize_vector(values):
    if len(values) != EMBEDDING_DIMENSIONS or any(not math.isfinite(v) for v in values):
        raise EmbeddingUnavailable("Embedding dimensions or values are invalid")
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 0:
        raise EmbeddingUnavailable("Embedding must not be zero")
    return [v / norm for v in values]


def format_input(value, task):
    if task == "RETRIEVAL_QUERY":
        return f"task: search result | query: {value}"
    if task == "RETRIEVAL_DOCUMENT":
        title, separator, body = value.partition("\n")
        return f"title: {title if separator else 'none'} | text: {body if separator else value}"
    raise ValueError("Unsupported embedding task")


class GoogleEmbedder:
    def __init__(self, cfg, *, indexing=False):
        self.model = cfg.embedding_model
        self.dimensions = cfg.embedding_dimension
        self.timeout = 30 if indexing else cfg.rag_embedding_timeout_seconds
        self.api_key = cfg.google_api_key

    def embed(self, texts, *, task):
        if not self.api_key:
            raise EmbeddingUnavailable("GOOGLE_API_KEY is required for semantic embeddings")
        # No hidden SDK retries: query deadlines must fit the voice tool's five-second budget.
        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                timeout=int(self.timeout * 1000), retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        try:
            response = client.models.embed_content(
                model=self.model,
                # Separate Content objects avoid Embedding 2 aggregating an entire batch.
                contents=[
                    types.Content(parts=[types.Part.from_text(text=format_input(value, task))])
                    for value in texts
                ],
                config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
            )
            rows = response.embeddings or []
            if len(rows) != len(texts):
                raise EmbeddingUnavailable("Embedding response count does not match inputs")
            return [normalize_vector(e.values or []) for e in rows]
        except EmbeddingUnavailable:
            raise
        except Exception as exc:
            # Do not include the provider URL, API key or customer query in error output.
            raise EmbeddingUnavailable(f"Embedding provider failed ({type(exc).__name__})") from None
        finally:
            client.close()
