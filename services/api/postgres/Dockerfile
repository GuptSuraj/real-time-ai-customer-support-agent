# Keep the original PostgreSQL 17 Alpine base so existing demo volumes remain compatible.
FROM postgres:17-alpine
ARG PGVECTOR_VERSION=0.8.7
RUN apk add --no-cache --virtual .pgvector-build-deps build-base curl \
    && curl -fsSL "https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v${PGVECTOR_VERSION}" -o /tmp/pgvector.tar.gz \
    && echo "cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85  /tmp/pgvector.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/pgvector.tar.gz -C /tmp \
    && make -C "/tmp/pgvector-${PGVECTOR_VERSION}" OPTFLAGS="" with_llvm=no \
    && make -C "/tmp/pgvector-${PGVECTOR_VERSION}" install with_llvm=no \
    && rm -rf /tmp/pgvector* \
    && apk del .pgvector-build-deps
