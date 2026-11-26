FROM registry.access.redhat.com/hi/python:3.12-builder@sha256:afb9e5506ae43c4812fd9f8d35897b08496e2fa617dd9cd9ba0b300a1f5e3355 AS builder

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

FROM registry.access.redhat.com/hi/python:3.12@sha256:6b1dfe7d49bd26204c8b965acc0e344b964d138c9679b0aff02875f2bd6aba63

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
