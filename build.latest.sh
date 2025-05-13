#!/bin/bash

unset KUBECONFIG

cd .. && docker build -f Dockerfile.latest \
             -t 2ylll/chatbot .

docker tag 2ylll/chatbot 2ylll/chatbot:$(date +%y%m%d)