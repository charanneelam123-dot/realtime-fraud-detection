# Optional local monitoring

With the API listening on port 8000, run `docker compose -f ops/compose.yaml up`.
Prometheus scrapes the application's `/metrics` endpoint. Add it to Grafana using
`http://prometheus:9090` as a Prometheus data source. These optional images have not
been run on this desktop because Docker is not installed. They are not deployed
by the free Render web-service Blueprint.

Request spans currently stay in process; there is no configured trace exporter.
The trace ID response header is useful for application correlation but is not
evidence that an external tracing backend has received data.
