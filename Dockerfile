FROM registry.access.redhat.com/ubi8/ubi-minimal:8.10-1018

ARG OC_CLI_VERSION=4.14

RUN microdnf install python3 shadow-utils tar gzip && \
    microdnf clean all

RUN groupadd -r -g 1000 bonfire && \
    useradd -r -u 1000 -g bonfire -m -d /opt/bonfire -s /bin/bash bonfire

RUN curl -L https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest-$OC_CLI_VERSION/openshift-client-linux.tar.gz \
  -o oc.tar.gz && \
  tar -C /usr/bin/ -xvzf oc.tar.gz oc kubectl && \
  rm -f oc.tar.gz

USER bonfire
WORKDIR /opt/bonfire
ENV PATH="/opt/bonfire/.local/bin:$PATH"

RUN pip3 install crc-bonfire --user
RUN bonfire config write-default
COPY entrypoint.sh .

ENTRYPOINT ["/opt/bonfire/entrypoint.sh"]
