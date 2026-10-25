---
sidebar_position: 3
---

# Kubernetes

Deploy Batchivo on Kubernetes for production-grade scalability.

## Prerequisites

- Kubernetes cluster (1.25+)
- kubectl configured
- Helm 3 (optional, for charts)

## Quick Start

```bash
# Apply namespace
kubectl apply -f infrastructure/k8s/namespace.yaml

# Create secrets
kubectl create secret generic backend-secrets \
  --from-literal=SECRET_KEY=$(openssl rand -base64 64) \
  --from-literal=DATABASE_URL=postgresql+psycopg://user:pass@postgres:5432/batchivo \
  -n batchivo

# Apply all manifests
kubectl apply -f infrastructure/k8s/ -n batchivo
```

## Manifests

### Namespace

```yaml
# infrastructure/k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: batchivo
```

### Backend Deployment

```yaml
# infrastructure/k8s/backend-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: batchivo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: backend
        image: ghcr.io/techize/batchivo-backend:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: backend-secrets
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
```

### Frontend Deployment

```yaml
# infrastructure/k8s/frontend-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: batchivo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
      - name: frontend
        image: ghcr.io/techize/batchivo-frontend:latest
        ports:
        - containerPort: 80
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "128Mi"
            cpu: "100m"
```

### Services

```yaml
# infrastructure/k8s/services.yaml
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: batchivo
spec:
  selector:
    app: backend
  ports:
  - port: 8000
    targetPort: 8000
---
apiVersion: v1
kind: Service
metadata:
  name: frontend
  namespace: batchivo
spec:
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 80
```

## Ingress

### nginx Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: batchivo
  namespace: batchivo
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - batchivo.example.com
    secretName: batchivo-tls
  rules:
  - host: batchivo.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: backend
            port:
              number: 8000
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend
            port:
              number: 80
```

## Database

For production, use a managed PostgreSQL service or deploy PostgreSQL with persistent storage.

### PostgreSQL StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: batchivo
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: batchivo
        - name: POSTGRES_USER
          value: batchivo
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secrets
              key: password
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

## Row-level security

PostgreSQL row-level security (RLS) is the database-level guard that keeps each tenant's rows
away from every other tenant. The policies are created by the migrations, but the application
only runs under them when `RLS_ENABLED` is `"true"` **and** `RLS_DATABASE_URL` points at the
non-superuser `app_user` role. Both ship off: `RLS_ENABLED: "false"` in
`infrastructure/k8s/backend/deployment.yaml`, and `rls_enabled = False` by default for local
development, where the application's own `tenant_id` filters do the isolating.

Turn it on in production in this order. Each step is safe on its own.

1. **Deploy the code with RLS still off.** Push to `main` and let Woodpecker and ArgoCD roll it
   out. The migrations up to `user_tenants_member_policy_v1` must be applied; with the flag off,
   the RLS context calls are no-ops, so nothing changes yet.
2. **Give `app_user` a password.** The role exists (created by migration `ecce200bf082`) but
   has no usable password until you set one:

   ```bash
   kubectl exec -it postgres-0 -n batchivo -- psql -U batchivo -d batchivo \
     -c "ALTER ROLE app_user WITH LOGIN PASSWORD '<strong-password>';"
   ```

3. **Create the `rls-credentials` secret.** The backend and Celery worker already reference it
   (as optional):

   ```bash
   kubectl create secret generic rls-credentials -n batchivo \
     --from-literal=RLS_DATABASE_URL='postgresql+psycopg://app_user:<strong-password>@postgres:5432/batchivo'
   ```

   Migrations keep using `DATABASE_URL` (the owner role), and so do the few deliberately
   cross-tenant paths: the platform admin console and the printer power-reading task.
4. **Review the commerce bridge.** `app/commerce_bridge.py` and its siblings run their own engine
   and role checks; confirm they behave under RLS before the flag flips.
5. **Flip the flag through git.** Change `RLS_ENABLED` to `"true"` in
   `infrastructure/k8s/backend/deployment.yaml`, push to `main`, and let ArgoCD sync. Never
   `kubectl apply` or `kubectl set env` by hand.
6. **Verify.** Log in, open a few tenant pages and the storefront, and check
   `kubectl logs -l app=backend -n batchivo` for permission errors. To roll back, set the flag to
   `"false"` through git again; no data changes either way.

:::warning
If `RLS_ENABLED` is `"true"` but the `rls-credentials` secret is missing or empty, the backend
**silently keeps using the owner connection**, which bypasses every policy. Confirm the secret
exists (`kubectl get secret rls-credentials -n batchivo`) before step 5.
:::

## Monitoring

Batchivo exposes Prometheus metrics at `/metrics` when `ENABLE_METRICS=true`.

```yaml
# ServiceMonitor for Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: batchivo-backend
  namespace: batchivo
spec:
  selector:
    matchLabels:
      app: backend
  endpoints:
  - port: http
    path: /metrics
```
