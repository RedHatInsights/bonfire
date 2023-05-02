FROM registry.access.redhat.com/ubi9/python-39

RUN pip install --upgrade pip && pip install crc-bonfire

COPY cicd/ /cicd/

WORKDIR /cicd

CMD ["./bootstrap.sh"]
