from python:3

run apt-get update && apt-get install -y bluez bluez-tools rfkill sudo

CMD ["systemctl", "start bluetooth.service"]
CMD ["systemctl", "enable bluetooth.service"]

ADD . .

RUN pip3 install -r requirements.txt && \
    rm -rv /root/.cache/pip


CMD ["python3", "./run.py"]
