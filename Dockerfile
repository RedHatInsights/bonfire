FROM registry.access.redhat.com/ubi8/ubi-minimal:8.7-1107

ARG OC_CLI_VERSION=4.12

RUN microdnf install python3 shadow-utils tar gzip

RUN groupadd -r -g 1000 bonfire && \
    useradd -r -u 1000 -g bonfire -m -d /opt/bonfire -s /bin/bash bonfire

RUN curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest-$OC_CLI_VERSION/openshift-client-linux.tar.gz \
  -o oc.tar.gz && \
  tar -C /usr/bin/ -xvzf oc.tar.gz oc && \
  rm -f oc.tar.gz

USER bonfire
WORKDIR /opt/bonfire

RUN python3 -m venv .venv
ENV PATH="/opt/bonfire/.venv/bin:$PATH"

RUN pip install crc-bonfire
RUN bonfire config write-default

CMD ["bonfire"]
