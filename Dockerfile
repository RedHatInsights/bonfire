FROM registry.access.redhat.com/hi/python:3.12-builder@sha256:9e8f996764dd3231cd49b6bc6847d4b2b6bbd140880c213a5a72e8ebe639dffb AS builder

ENV OC_CLI_VERSION=4.16

USER 0
RUN dnf install -y git-core tar gzip && dnf clean all
USER 65532

WORKDIR /opt/app-root/src

COPY --chown=65532:0 . .

RUN git config --global --add safe.directory /opt/app-root/src && \
    python3.12 -m venv .venv && \
    .venv/bin/pip install -U pip build && \
    .venv/bin/python3.12 -m build -o dist && \
    WHEEL=$(ls dist/crc_bonfire-*.whl) && \
    .venv/bin/pip install "$WHEEL"

RUN curl -sSLO https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest-$OC_CLI_VERSION/openshift-client-linux.tar.gz && \
    tar -xzf openshift-client-linux.tar.gz oc kubectl && \
    rm openshift-client-linux.tar.gz

RUN HOME=/opt/app-root/src .venv/bin/bonfire config write-default

FROM registry.access.redhat.com/hi/python:3.12@sha256:7f4cfba00a0d385d4616671845e9ecf3e5e8019b6610abcd52db5061a1b43aea

WORKDIR /opt/app-root/src

ENV HOME=/opt/app-root/src \
    PATH=/opt/app-root/src/.venv/bin:/opt/app-root/src/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    LANG=en_US.UTF-8

COPY --from=builder --chown=65532:0 /opt/app-root/src/.venv/ .venv/
COPY --from=builder --chown=65532:0 /opt/app-root/src/oc .local/bin/oc
COPY --from=builder --chown=65532:0 /opt/app-root/src/kubectl .local/bin/kubectl
COPY --from=builder --chown=65532:0 /opt/app-root/src/.config/ .config/
COPY --chown=65532:0 entrypoint.py .

ENTRYPOINT ["python3", "entrypoint.py"]
