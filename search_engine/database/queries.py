# Select random images from cache that the user hasn't seen yet
GET_UNSEEN_IMAGES = """
    SELECT image_url, source, thumbnail_url, title
    FROM image_cache
    WHERE query = $1 
      AND is_dead = FALSE
      AND image_url NOT IN (
          SELECT image_url FROM user_seen_images 
          WHERE user_id = $2 AND query = $1
      )
    ORDER BY RANDOM()
    LIMIT $3
"""

# Track that a user has seen these images
MARK_AS_SEEN = """
    INSERT INTO user_seen_images (user_id, query, image_url)
    VALUES ($1, $2, $3)
    ON CONFLICT (user_id, query, image_url) DO NOTHING
"""

INSERT_CACHED_IMAGE = """
    INSERT INTO image_cache (query, image_url, source, thumbnail_url, title)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (query, image_url) DO NOTHING
"""

MARK_IMAGES_DEAD = """
    UPDATE image_cache
    SET is_dead = TRUE
    WHERE image_url = ANY($1)
"""

GET_STALE_IMAGES = """
    SELECT image_url
    FROM image_cache
    WHERE is_dead = FALSE
    AND last_validated < NOW() - INTERVAL '24 hours'
    LIMIT $1
"""

UPDATE_VALIDATION_TIME = """
    UPDATE image_cache
    SET last_validated = NOW()
    WHERE image_url = ANY($1)
"""

INSERT_SEARCH_HISTORY = """
    INSERT INTO search_history (user_id, query) VALUES ($1, $2)
"""