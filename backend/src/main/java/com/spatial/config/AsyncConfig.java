package com.spatial.config;

import java.util.concurrent.Executor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

@Configuration
@EnableAsync
public class AsyncConfig {

    /**
     * Jobs run one at a time by default (JOB_CONCURRENCY=1). A reconstruction can use several GB of RAM, and on a laptop with
     * integrated graphics the GPU shares that memory, so two parallel jobs could exhaust it. The AI service enforces the same
     * limit on its side. Raise it only if the AI service runs on a bigger machine.
     */
    @Bean("jobExecutor")
    public Executor jobExecutor(@Value("${app.job-concurrency:1}") int concurrency) {
        int n = Math.max(1, concurrency);
        ThreadPoolTaskExecutor ex = new ThreadPoolTaskExecutor();
        ex.setCorePoolSize(n);
        ex.setMaxPoolSize(n);
        ex.setQueueCapacity(100);
        ex.setThreadNamePrefix("job-");
        ex.initialize();
        return ex;
    }
}
