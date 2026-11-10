package com.spatial.domain;

import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, UUID> {
    Optional<User> findByEmailIgnoreCase(String email);

    /** Used only by the development-access bypass to pick an existing account. */
    Optional<User> findFirstByOrderByCreatedAtAsc();
}
