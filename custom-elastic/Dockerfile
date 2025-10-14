# Use the official Elasticsearch image as the base
# It's best to specify an exact version for consistency
FROM docker.elastic.co/elasticsearch/elasticsearch:9.1.4

# Use the RUN command to execute the plugin installation script
# This command is run when you build the image
RUN bin/elasticsearch-plugin install analysis-icu