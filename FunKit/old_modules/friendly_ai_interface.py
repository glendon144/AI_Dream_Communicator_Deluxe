ross@Whitebook:~$ # 1) See what models LocalAI thinks are available
curl -s http://localhost:8080/v1/models | jq

# 2) Try the smallest valid chat request with explicit max_tokens
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-local" \
  -d '{
    "model": "mistral-7b-instruct",
    "max_tokens": 128,
    "messages": [{"role":"user","content":"Reply with the single word: OK"}]
  }' | jq

# 3) Watch server logs while you click ASK in FunKit
docker logs -f localai
{
  "object": "list",
  "data": [
    {
      "id": "mistral-7b-instruct-v0.2.Q4_K_M.gguf",
      "object": "model"
    }
  ]
}
{
  "error": {
    "code": 400,
    "message": "Bad Request",
    "type": ""
  }
}
permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Get "http://%2Fvar%2Frun%2Fdocker.sock/v1.49/containers/localai/json": dial unix /var/run/docker.sock: connect: permission denied
gross@Whitebook:~$ 


