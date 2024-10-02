FROM registry.access.redhat.com/ubi9/python-312:1-25.1726664318 as builder

ENV OC_CLI_VERSION=4.16

COPY --chown=default:0 . .

RUN pip install build
RUN python -m build -o dist

RUN curl -sSLO https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest-$OC_CLI_VERSION/openshift-client-linux.tar.gz && \
  tar -xzf openshift-client-linux.tar.gz oc kubectl && \
  rm openshift-client-linux.tar.gz

FROM registry.access.redhat.com/ubi9-minimal:9.4-1227.1726694542

ENV APP_ROOT=/opt/bonfire

ENV PYTHON_VERSION=3.12 \
    PATH=$APP_ROOT/.local/bin/:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    LANG=en_US.UTF-8 \
    CNB_USER_ID=1001 \
    CNB_GROUP_ID=0 \
    PIP_NO_CACHE_DIR=off

RUN microdnf install -y python3.12 python3.12-pip shadow-utils && \
    microdnf clean all

RUN useradd -r -u 1001 -g 0 -m -d $APP_ROOT -s /bin/bash bonfire

USER 1001
WORKDIR $APP_ROOT

COPY --from=builder /opt/app-root/src/dist/crc_bonfire*.whl .

RUN pip3.12 install crc_bonfire*.whl && rm crc_bonfire*.whl

COPY --from=builder /opt/app-root/src/oc /opt/app-root/src/kubectl ${APP_ROOT}/.local/bin/
COPY entrypoint.sh .

RUN bonfire config write-default

ENTRYPOINT [ "./entrypoint.sh" ]