-- Appointment Booking System - Database Schema
-- Tüm tabloları oluşturur

-- 1. businesses tablosu - İşletmeler (tenant'lar)
CREATE TABLE IF NOT EXISTS businesses (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50),
    address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. users tablosu - Kullanıcılar (business owner/admin/staff)
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role ENUM('owner', 'admin', 'staff') NOT NULL DEFAULT 'staff',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    INDEX idx_business_id (business_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. customers tablosu - Müşteriler
CREATE TABLE IF NOT EXISTS customers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    full_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    UNIQUE KEY unique_business_email (business_id, email),
    INDEX idx_business_id (business_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. services tablosu - Hizmetler
CREATE TABLE IF NOT EXISTS services (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    duration_minutes INT NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    INDEX idx_business_id (business_id),
    INDEX idx_is_active (is_active),
    UNIQUE KEY unique_business_service_name (business_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mevcut DB için ALTER TABLE komutu (eğer tablo zaten varsa):
-- ALTER TABLE services ADD UNIQUE KEY unique_business_service_name (business_id, name);

-- 5. staff tablosu - Personel
CREATE TABLE IF NOT EXISTS staff (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    user_id INT NULL,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_business_id (business_id),
    INDEX idx_is_active (is_active),
    UNIQUE KEY unique_business_staff_email (business_id, email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mevcut DB için ALTER TABLE komutu (eğer tablo zaten varsa):
-- ALTER TABLE staff ADD UNIQUE KEY unique_business_staff_email (business_id, email);

-- 6. appointments tablosu - Randevular
CREATE TABLE IF NOT EXISTS appointments (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    customer_id INT NOT NULL,
    staff_id INT NOT NULL,
    appointment_date DATETIME NOT NULL,
    status ENUM('pending', 'scheduled', 'completed', 'cancelled', 'rejected', 'no_show') NOT NULL DEFAULT 'scheduled',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE,
    INDEX idx_business_id (business_id),
    INDEX idx_staff_id (staff_id),
    INDEX idx_customer_id (customer_id),
    INDEX idx_appointment_date (appointment_date),
    INDEX idx_status (status),
    INDEX idx_business_staff_date (business_id, staff_id, appointment_date),
    INDEX idx_business_status_date (business_id, status, appointment_date),
    UNIQUE KEY unique_business_staff_datetime (business_id, staff_id, appointment_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mevcut DB için ALTER TABLE komutu (eğer tablo zaten varsa):
-- ALTER TABLE appointments ADD UNIQUE KEY unique_business_staff_datetime (business_id, staff_id, appointment_date);

-- Not: Buffer time kontrolü application seviyesinde yapılacak

-- 7. appointment_services tablosu - Randevu-Hizmet ilişkisi (çoklu hizmet)
CREATE TABLE IF NOT EXISTS appointment_services (
    id INT PRIMARY KEY AUTO_INCREMENT,
    appointment_id INT NOT NULL,
    service_id INT NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
    FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
    INDEX idx_appointment_id (appointment_id),
    INDEX idx_service_id (service_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. staff_day_locks tablosu - Boş gün race condition önleme için deterministic lock
-- Not: Bu tablo operational cleanup gerektirir. 180 günden eski kayıtlar periyodik olarak
-- silinebilir (örn. cron job ile: DELETE FROM staff_day_locks WHERE day_date < DATE_SUB(CURDATE(), INTERVAL 180 DAY))
CREATE TABLE IF NOT EXISTS staff_day_locks (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    staff_id INT NOT NULL,
    day_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE,
    UNIQUE KEY unique_business_staff_day (business_id, staff_id, day_date),
    INDEX idx_business_staff_day (business_id, staff_id, day_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mevcut DB için ALTER TABLE komutu (eğer tablo zaten varsa):
-- CREATE TABLE IF NOT EXISTS staff_day_locks (...);

-- 9. transactions tablosu - İşlemler/Ödemeler
CREATE TABLE IF NOT EXISTS transactions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    appointment_id INT NULL,
    customer_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    payment_method ENUM('cash', 'card', 'online') NOT NULL,
    status ENUM('pending', 'completed', 'refunded') NOT NULL DEFAULT 'pending',
    idempotency_key VARCHAR(64) NULL,
    transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE SET NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    INDEX idx_business_id (business_id),
    INDEX idx_appointment_id (appointment_id),
    INDEX idx_customer_id (customer_id),
    INDEX idx_status (status),
    INDEX idx_transaction_date (transaction_date),
    -- Duplicate önleme: appointment_id NOT NULL ise (business_id, appointment_id, payment_method, amount, status) unique
    UNIQUE KEY unique_business_appointment_payment (business_id, appointment_id, payment_method, amount, status),
    -- Idempotency kontrolü: appointment_id NULL olanlar için idempotency_key ile duplicate önleme
    UNIQUE KEY unique_business_idempotency (business_id, idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mevcut DB için ALTER TABLE komutları (eğer tablo zaten varsa):
-- ALTER TABLE transactions ADD COLUMN idempotency_key VARCHAR(64) NULL;
-- ALTER TABLE transactions ADD UNIQUE KEY unique_business_appointment_payment (business_id, appointment_id, payment_method, amount, status);
-- ALTER TABLE transactions ADD UNIQUE KEY unique_business_idempotency (business_id, idempotency_key);

-- 9. business_settings tablosu - İşletme Ayarları
CREATE TABLE IF NOT EXISTS business_settings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL UNIQUE,
    slot_length_minutes INT DEFAULT 30,
    buffer_time_minutes INT DEFAULT 15,
    cancellation_hours INT DEFAULT 24,
    working_hours_start TIME DEFAULT '09:00:00',
    working_hours_end TIME DEFAULT '18:00:00',
    timezone VARCHAR(50) DEFAULT 'Europe/Istanbul',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 10. booking_links tablosu - Public Booking Links
CREATE TABLE IF NOT EXISTS booking_links (
    id INT PRIMARY KEY AUTO_INCREMENT,
    business_id INT NOT NULL,
    token VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    service_ids JSON NULL COMMENT 'NULL = all services, otherwise array of service IDs',
    staff_ids JSON NULL COMMENT 'NULL = all staff, otherwise array of staff IDs',
    start_date DATE NULL COMMENT 'NULL = no start date restriction',
    end_date DATE NULL COMMENT 'NULL = no end date restriction',
    max_uses INT NULL COMMENT 'NULL = unlimited uses',
    current_uses INT NOT NULL DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    INDEX idx_business_id (business_id),
    INDEX idx_token (token),
    INDEX idx_is_active (is_active),
    INDEX idx_business_active (business_id, is_active),
    INDEX idx_date_range (start_date, end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

