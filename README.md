```
docker network create mongo-network
```


```Docker
docker run -d \
  --name mongo \
  --network mongo-network \
  -e MONGO_INITDB_ROOT_USERNAME=root \
  -e MONGO_INITDB_ROOT_PASSWORD=possword \
  -p 27017:27017 \
  --restart always \
  mongo:latest
```

```
docker run -d \
  --name mongo-express \
  --network mongo-network \
  -e ME_CONFIG_MONGODB_URL="mongodb://root:password@mongo:27017/" \
  -e ME_CONFIG_MONGODB_ENABLE_ADMIN="true" \
  -p 8081:8081 \
  --restart always \
  mongo-express:latest
```

