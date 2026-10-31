FROM xserrat/facebook-demucs:latest

ENTRYPOINT []

RUN pip3 install --upgrade minio redis requests

WORKDIR /srv
COPY worker-server.py /srv/

CMD ["python3", "-u", "worker-server.py"]
