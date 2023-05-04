FROM registry.access.redhat.com/ubi8/ubi-minimal:8.7-1107

USER bonfire
WORKDIR /opt/bonfire

RUN pip install --upgrade pip && pip install crc-bonfire

COPY cicd/ /bonfire/

CMD ["./bootstrap.sh"]
