# Use the official Elasticsearch image as the base
# It's best to specify an exact version for consistency
FROM docker.elastic.co/elasticsearch/elasticsearch:9.1.4

# Install ICU analysis plugin (required for icu_tokenizer + icu_folding).
# --batch makes it non-interactive during docker build.
RUN bin/elasticsearch-plugin install --batch analysis-icu