import requests

res = requests.post("http://127.0.0.1:6341/chat", params={"question":"简述支付机构监管的核心要求"})
print(res.json()["answer"])
