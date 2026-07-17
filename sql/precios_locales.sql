CREATE DATABASE IF NOT EXISTS precios_locales
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE precios_locales;

CREATE TABLE validation_settings (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_personal BIGINT UNSIGNED NOT NULL,
    max_auto_price_change_percent DECIMAL(6,2) NOT NULL DEFAULT 10.00,
    min_material_confidence DECIMAL(5,2) NOT NULL DEFAULT 70.00,
    min_price_confidence DECIMAL(5,2) NOT NULL DEFAULT 70.00,
    allow_symbol_space_autocorrect BOOLEAN NOT NULL DEFAULT TRUE,
    require_review_for_new_material BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_validation_personal (id_personal)
);

CREATE TABLE materials (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_personal BIGINT UNSIGNED NOT NULL,
    canonical_name VARCHAR(180) NOT NULL,
    normalized_name VARCHAR(180) NOT NULL,
    section ENUM('EXPORTACION', 'NACIONAL', 'OTRO') NOT NULL DEFAULT 'OTRO',
    source ENUM('reviewed', 'manual') NOT NULL DEFAULT 'reviewed',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_document_id BIGINT UNSIGNED NULL,
    first_seen_row_id BIGINT UNSIGNED NULL,
    approved_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_material_personal_section_name (id_personal, section, normalized_name),
    INDEX idx_material_personal (id_personal),
    INDEX idx_material_section (section),
    INDEX idx_material_active (active)
);

CREATE TABLE material_aliases (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_personal BIGINT UNSIGNED NOT NULL,
    material_id BIGINT UNSIGNED NOT NULL,
    section ENUM('EXPORTACION', 'NACIONAL', 'OTRO') NOT NULL DEFAULT 'OTRO',
    alias_text VARCHAR(180) NOT NULL,
    normalized_alias VARCHAR(180) NOT NULL,
    source ENUM('reviewed', 'manual', 'system') NOT NULL DEFAULT 'reviewed',
    match_rule ENUM('exact', 'symbol_space_variant', 'manual_link') NOT NULL DEFAULT 'manual_link',
    confidence DECIMAL(5,2) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_alias_material FOREIGN KEY (material_id) REFERENCES materials(id),
    UNIQUE KEY uq_alias_personal_section (id_personal, section, normalized_alias),
    INDEX idx_alias_material (material_id),
    INDEX idx_alias_personal (id_personal)
);

CREATE TABLE ocr_documents (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_personal BIGINT UNSIGNED NOT NULL,
    status ENUM('pending_review', 'processed', 'rejected', 'failed') NOT NULL DEFAULT 'pending_review',
    engine VARCHAR(50) NOT NULL,
    template VARCHAR(100) NULL,
    detected_date DATE NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME NULL,
    reviewed_at DATETIME NULL,
    original_filename VARCHAR(255) NULL,
    compressed_image_path VARCHAR(500) NOT NULL,
    compressed_image_mime VARCHAR(50) NULL,
    compressed_image_size INT UNSIGNED NULL,
    original_image_size INT UNSIGNED NULL,
    image_sha256 CHAR(64) NULL,
    raw_ocr_json JSON NOT NULL,
    reviewed_json JSON NULL,
    template_compatible BOOLEAN NULL,
    total_rows INT UNSIGNED NOT NULL DEFAULT 0,
    rows_requiring_review INT UNSIGNED NOT NULL DEFAULT 0,
    prices_detected INT UNSIGNED NOT NULL DEFAULT 0,
    error_message TEXT NULL,
    review_notes TEXT NULL,
    INDEX idx_documents_personal_status (id_personal, status),
    INDEX idx_documents_personal_date (id_personal, detected_date),
    INDEX idx_documents_personal_date_status (id_personal, detected_date, status),
    INDEX idx_documents_uploaded_at (uploaded_at),
    INDEX idx_documents_image_sha256 (image_sha256)
);

CREATE TABLE ocr_document_rows (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT UNSIGNED NOT NULL,
    id_personal BIGINT UNSIGNED NOT NULL,
    section ENUM('EXPORTACION', 'NACIONAL', 'OTRO') NOT NULL DEFAULT 'OTRO',
    row_number INT UNSIGNED NOT NULL,
    material_raw VARCHAR(180) NULL,
    material_ocr VARCHAR(180) NULL,
    material_normalized VARCHAR(180) NULL,
    suggested_material_id BIGINT UNSIGNED NULL,
    approved_material_id BIGINT UNSIGNED NULL,
    price_text VARCHAR(50) NULL,
    price_value INT NULL,
    approved_price_value INT NULL,
    material_confidence DECIMAL(5,2) NULL,
    price_confidence DECIMAL(5,2) NULL,
    match_type ENUM('exact_alias', 'exact_material', 'symbol_space_variant', 'possible_text_change', 'new_material', 'no_match') NULL,
    match_score DECIMAL(5,2) NULL,
    requires_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason ENUM('none', 'new_material', 'possible_material_match', 'text_changed', 'price_out_of_range', 'low_material_confidence', 'low_price_confidence', 'invalid_price', 'ocr_requires_review') NOT NULL DEFAULT 'none',
    validation_status ENUM('valid', 'auto_corrected', 'pending_review', 'approved', 'corrected', 'rejected') NOT NULL DEFAULT 'valid',
    validation_notes TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at DATETIME NULL,
    CONSTRAINT fk_row_document FOREIGN KEY (document_id) REFERENCES ocr_documents(id),
    CONSTRAINT fk_row_suggested_material FOREIGN KEY (suggested_material_id) REFERENCES materials(id),
    CONSTRAINT fk_row_approved_material FOREIGN KEY (approved_material_id) REFERENCES materials(id),
    UNIQUE KEY uq_document_section_row (document_id, section, row_number),
    INDEX idx_rows_personal_document (id_personal, document_id),
    INDEX idx_rows_material_normalized (material_normalized),
    INDEX idx_rows_requires_review (requires_review),
    INDEX idx_rows_validation_status (validation_status),
    INDEX idx_rows_review_reason (review_reason)
);

ALTER TABLE materials
    ADD CONSTRAINT fk_material_first_seen_document
        FOREIGN KEY (first_seen_document_id)
        REFERENCES ocr_documents(id);

ALTER TABLE materials
    ADD CONSTRAINT fk_material_first_seen_row
        FOREIGN KEY (first_seen_row_id)
        REFERENCES ocr_document_rows(id);

CREATE TABLE price_history (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT UNSIGNED NOT NULL,
    document_row_id BIGINT UNSIGNED NOT NULL,
    id_personal BIGINT UNSIGNED NOT NULL,
    material_id BIGINT UNSIGNED NOT NULL,
    observed_date DATE NOT NULL,
    section ENUM('EXPORTACION', 'NACIONAL', 'OTRO') NOT NULL DEFAULT 'OTRO',
    price_value INT NOT NULL,
    price_text VARCHAR(50) NULL,
    source ENUM('ocr', 'reviewed') NOT NULL DEFAULT 'ocr',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_price_document FOREIGN KEY (document_id) REFERENCES ocr_documents(id),
    CONSTRAINT fk_price_row FOREIGN KEY (document_row_id) REFERENCES ocr_document_rows(id),
    CONSTRAINT fk_price_material FOREIGN KEY (material_id) REFERENCES materials(id),
    UNIQUE KEY uq_price_document_row (document_row_id),
    INDEX idx_price_personal_material_date (id_personal, material_id, observed_date),
    INDEX idx_price_personal_date (id_personal, observed_date),
    INDEX idx_price_material_date (material_id, observed_date)
);

CREATE TABLE ocr_review_events (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT UNSIGNED NOT NULL,
    document_row_id BIGINT UNSIGNED NULL,
    id_personal BIGINT UNSIGNED NOT NULL,
    action ENUM('approved_document', 'rejected_document', 'approved_row', 'corrected_row', 'created_material', 'linked_material', 'created_alias', 'corrected_material', 'corrected_price') NOT NULL,
    previous_value JSON NULL,
    new_value JSON NULL,
    notes TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_review_document FOREIGN KEY (document_id) REFERENCES ocr_documents(id),
    CONSTRAINT fk_review_row FOREIGN KEY (document_row_id) REFERENCES ocr_document_rows(id),
    INDEX idx_review_document (document_id),
    INDEX idx_review_row (document_row_id),
    INDEX idx_review_personal_created (id_personal, created_at)
);
