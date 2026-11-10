package com.spatial.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.spatial.config.AppProps;
import java.time.Duration;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

@Component
public class AiClient {
    private final RestClient client;
    private final ObjectMapper mapper = new ObjectMapper();

    public AiClient(AppProps props) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(10_000);
        factory.setReadTimeout((int) Duration.ofHours(3).toMillis());
        this.client = RestClient.builder().baseUrl(props.aiUrl()).requestFactory(factory).build();
    }

    public JsonNode post(String path, Object body) {
        try {
            return client.post().uri(path).contentType(MediaType.APPLICATION_JSON).body(body).retrieve().body(JsonNode.class);
        } catch (RestClientResponseException e) {
            throw new AiException(e.getStatusCode().value(), detailOf(e));
        } catch (RestClientException e) {
            throw new AiException(503, "AI service unreachable: " + e.getMessage());
        }
    }

    public JsonNode get(String path) {
        try {
            return client.get().uri(path).retrieve().body(JsonNode.class);
        } catch (RestClientException e) {
            throw new AiException(503, "AI service unreachable: " + e.getMessage());
        }
    }

    private String detailOf(RestClientResponseException e) {
        try {
            JsonNode n = mapper.readTree(e.getResponseBodyAsString());
            if (n.hasNonNull("detail")) {
                return n.get("detail").asText();
            }
        } catch (Exception ignored) {
        }
        return "AI service error " + e.getStatusCode().value();
    }
}
