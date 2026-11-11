FROM postgres:17-alpine
# Copy into the image: host filesystem mount permissions no longer affect execution.
# The official entrypoint sources non-executable .sh files.
COPY --chmod=0644 init-db.sh /docker-entrypoint-initdb.d/10-app-role.sh
