-- seed.sql - Appointment Booking System (Comprehensive)
-- MySQL 8+ recommended
-- Password: test123
-- bcrypt hash: $2b$12$bhhxMO1y1eEgiTadJPaD4e5jxN5GfWoQYn6Ney1UiXL2cHSrh24te

-- ------------------------------------------------------------
-- (OPTIONAL) CLEANUP - Uncomment if you want a full reset
-- ------------------------------------------------------------
SET FOREIGN_KEY_CHECKS = 0;

-- TRUNCATE TABLE appointment_services;
-- TRUNCATE TABLE transactions;
-- TRUNCATE TABLE staff_day_locks;
-- TRUNCATE TABLE appointments;
-- TRUNCATE TABLE booking_links;
-- TRUNCATE TABLE business_settings;
-- TRUNCATE TABLE staff;
-- TRUNCATE TABLE services;
-- TRUNCATE TABLE customers;
-- TRUNCATE TABLE users;
-- TRUNCATE TABLE businesses;

SET FOREIGN_KEY_CHECKS = 1;

-- ------------------------------------------------------------
-- CONSTANTS
-- ------------------------------------------------------------
SET @PWD_HASH = '$2b$12$bhhxMO1y1eEgiTadJPaD4e5jxN5GfWoQYn6Ney1UiXL2cHSrh24te';

-- ============================================================
-- BUSINESS #1
-- ============================================================
INSERT INTO businesses (name, email, phone, address)
VALUES ('Test Salon Istanbul', 'b1@test-salon.com', '05550000001', 'İstanbul, Türkiye');

SET @B1 = LAST_INSERT_ID();

-- Users (1 owner + 2 admin + 1 staff user)
INSERT INTO users (business_id, email, password_hash, full_name, role) VALUES
(@B1, 'b1.owner@test.com', @PWD_HASH, 'B1 Owner', 'owner'),
(@B1, 'b1.admin1@test.com', @PWD_HASH, 'B1 Admin 1', 'admin'),
(@B1, 'b1.admin2@test.com', @PWD_HASH, 'B1 Admin 2', 'admin'),
(@B1, 'b1.staffuser1@test.com', @PWD_HASH, 'B1 StaffUser 1', 'staff');

SET @B1_OWNER  = (SELECT id FROM users WHERE business_id=@B1 AND email='b1.owner@test.com' LIMIT 1);
SET @B1_ADMIN1 = (SELECT id FROM users WHERE business_id=@B1 AND email='b1.admin1@test.com' LIMIT 1);
SET @B1_ADMIN2 = (SELECT id FROM users WHERE business_id=@B1 AND email='b1.admin2@test.com' LIMIT 1);
SET @B1_SU1    = (SELECT id FROM users WHERE business_id=@B1 AND email='b1.staffuser1@test.com' LIMIT 1);

-- Customers (5)
INSERT INTO customers (business_id, email, phone, full_name) VALUES
(@B1, 'b1.customer1@test.com', '05551111111', 'B1 Customer 1'),
(@B1, 'b1.customer2@test.com', '05552222222', 'B1 Customer 2'),
(@B1, 'b1.customer3@test.com', '05553333333', 'B1 Customer 3'),
(@B1, 'b1.customer4@test.com', '05554444444', 'B1 Customer 4'),
(@B1, 'b1.customer5@test.com', '05555555555', 'B1 Customer 5');

SET @B1_C1 = (SELECT id FROM customers WHERE business_id=@B1 AND email='b1.customer1@test.com' LIMIT 1);
SET @B1_C2 = (SELECT id FROM customers WHERE business_id=@B1 AND email='b1.customer2@test.com' LIMIT 1);
SET @B1_C3 = (SELECT id FROM customers WHERE business_id=@B1 AND email='b1.customer3@test.com' LIMIT 1);
SET @B1_C4 = (SELECT id FROM customers WHERE business_id=@B1 AND email='b1.customer4@test.com' LIMIT 1);
SET @B1_C5 = (SELECT id FROM customers WHERE business_id=@B1 AND email='b1.customer5@test.com' LIMIT 1);

-- Services (6, include 1 inactive)
INSERT INTO services (business_id, name, description, duration_minutes, price, is_active) VALUES
(@B1, 'Haircut',        'Classic haircut',               30, 150.00, 1),
(@B1, 'Hair Coloring',  'Full hair coloring',           120, 900.00, 1),
(@B1, 'Blow Dry',       'Styling / blow dry',            45, 250.00, 1),
(@B1, 'Hair Treatment', 'Deep care treatment',           60, 400.00, 1),
(@B1, 'Beard Trim',     'Classic beard trim',            20, 120.00, 1),
(@B1, 'Old Service X',  'Inactive legacy service',       30,  99.00, 0);

SET @B1_SVC1 = (SELECT id FROM services WHERE business_id=@B1 AND name='Haircut' LIMIT 1);
SET @B1_SVC2 = (SELECT id FROM services WHERE business_id=@B1 AND name='Hair Coloring' LIMIT 1);
SET @B1_SVC3 = (SELECT id FROM services WHERE business_id=@B1 AND name='Blow Dry' LIMIT 1);
SET @B1_SVC4 = (SELECT id FROM services WHERE business_id=@B1 AND name='Hair Treatment' LIMIT 1);
SET @B1_SVC5 = (SELECT id FROM services WHERE business_id=@B1 AND name='Beard Trim' LIMIT 1);
SET @B1_SVC6 = (SELECT id FROM services WHERE business_id=@B1 AND name='Old Service X' LIMIT 1);

-- Staff (3) - 2 of them linked to users; 1 is non-panel staff
-- Also demonstrates: staff can be "admin" user in users table (panel access) if you link it
INSERT INTO staff (business_id, user_id, full_name, email, phone, is_active) VALUES
(@B1, @B1_SU1,    'B1 Staff 1', 'b1.staff1@test.com', '05556660001', 1),
(@B1, @B1_ADMIN1, 'B1 Staff 2 (Admin)', 'b1.staff2@test.com', '05556660002', 1),
(@B1, NULL,       'B1 Staff 3 (No Panel)', 'b1.staff3@test.com', '05556660003', 1);

SET @B1_ST1 = (SELECT id FROM staff WHERE business_id=@B1 AND email='b1.staff1@test.com' LIMIT 1);
SET @B1_ST2 = (SELECT id FROM staff WHERE business_id=@B1 AND email='b1.staff2@test.com' LIMIT 1);
SET @B1_ST3 = (SELECT id FROM staff WHERE business_id=@B1 AND email='b1.staff3@test.com' LIMIT 1);

-- Business settings
INSERT INTO business_settings (business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours, working_hours_start, working_hours_end, timezone)
VALUES (@B1, 30, 15, 24, '09:00:00', '19:00:00', 'Europe/Istanbul');

-- Staff day locks (examples)
INSERT INTO staff_day_locks (business_id, staff_id, day_date) VALUES
(@B1, @B1_ST1, DATE_ADD(CURDATE(), INTERVAL 2 DAY)),
(@B1, @B1_ST2, DATE_ADD(CURDATE(), INTERVAL 2 DAY)),
(@B1, @B1_ST3, DATE_ADD(CURDATE(), INTERVAL 5 DAY)),
(@B1, @B1_ST1, DATE_SUB(CURDATE(), INTERVAL 10 DAY));

-- Booking links (3 examples)
-- 1) Active, all services + all staff (NULL JSON)
INSERT INTO booking_links (business_id, token, name, description, service_ids, staff_ids, start_date, end_date, max_uses, current_uses, is_active)
VALUES
(@B1, 'b1_token_all_001', 'B1 - General Booking Link', 'All staff & all services', NULL, NULL,
 DATE_SUB(CURDATE(), INTERVAL 30 DAY), DATE_ADD(CURDATE(), INTERVAL 60 DAY), NULL, 3, 1);

-- 2) Active, filtered services & staff, usage limited
INSERT INTO booking_links (business_id, token, name, description, service_ids, staff_ids, start_date, end_date, max_uses, current_uses, is_active)
VALUES
(@B1, 'b1_token_filtered_001', 'B1 - Coloring Special', 'Only Hair Coloring + Treatment, Staff1 & Staff2', JSON_ARRAY(@B1_SVC2, @B1_SVC4), JSON_ARRAY(@B1_ST1, @B1_ST2),
 DATE_SUB(CURDATE(), INTERVAL 7 DAY), DATE_ADD(CURDATE(), INTERVAL 14 DAY), 10, 2, 1);

-- 3) Inactive / expired
INSERT INTO booking_links (business_id, token, name, description, service_ids, staff_ids, start_date, end_date, max_uses, current_uses, is_active)
VALUES
(@B1, 'b1_token_expired_001', 'B1 - Expired Link', 'Expired example', JSON_ARRAY(@B1_SVC1), JSON_ARRAY(@B1_ST3),
 DATE_SUB(CURDATE(), INTERVAL 60 DAY), DATE_SUB(CURDATE(), INTERVAL 30 DAY), 5, 5, 0);

-- ------------------------------------------------------------
-- B1 APPOINTMENTS (3 staff x 10 = 30)
-- Notes are UNIQUE tags so we can reference later easily.
-- Ensure unique datetime per staff to satisfy unique_business_staff_datetime.
-- ------------------------------------------------------------

-- Staff 1 appointments (10)
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@B1, @B1_C1, @B1_ST1, CONCAT(CURDATE(), ' 09:00:00'), 'completed', 'B1-S1-A01 completed today'),
(@B1, @B1_C2, @B1_ST1, CONCAT(CURDATE(), ' 10:00:00'), 'scheduled', 'B1-S1-A02 scheduled today'),
(@B1, @B1_C3, @B1_ST1, CONCAT(CURDATE(), ' 11:00:00'), 'pending',   'B1-S1-A03 pending request'),
(@B1, @B1_C4, @B1_ST1, CONCAT(CURDATE(), ' 12:00:00'), 'cancelled', 'B1-S1-A04 cancelled today'),
(@B1, @B1_C5, @B1_ST1, CONCAT(CURDATE(), ' 13:00:00'), 'no_show',   'B1-S1-A05 no show today'),
(@B1, @B1_C1, @B1_ST1, CONCAT(DATE_SUB(CURDATE(), INTERVAL 2 DAY), ' 10:30:00'), 'completed', 'B1-S1-A06 completed -2d'),
(@B1, @B1_C2, @B1_ST1, CONCAT(DATE_SUB(CURDATE(), INTERVAL 7 DAY), ' 16:00:00'), 'rejected',  'B1-S1-A07 rejected -7d'),
(@B1, @B1_C3, @B1_ST1, CONCAT(DATE_SUB(CURDATE(), INTERVAL 14 DAY), ' 14:00:00'), 'completed', 'B1-S1-A08 completed -14d'),
(@B1, @B1_C4, @B1_ST1, CONCAT(DATE_ADD(CURDATE(), INTERVAL 3 DAY), ' 11:30:00'), 'scheduled', 'B1-S1-A09 scheduled +3d'),
(@B1, @B1_C5, @B1_ST1, CONCAT(DATE_ADD(CURDATE(), INTERVAL 9 DAY), ' 15:00:00'), 'pending',   'B1-S1-A10 pending +9d');

-- Staff 2 appointments (10)
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@B1, @B1_C2, @B1_ST2, CONCAT(CURDATE(), ' 09:30:00'), 'completed', 'B1-S2-A01 completed today'),
(@B1, @B1_C3, @B1_ST2, CONCAT(CURDATE(), ' 10:30:00'), 'scheduled', 'B1-S2-A02 scheduled today'),
(@B1, @B1_C4, @B1_ST2, CONCAT(CURDATE(), ' 11:30:00'), 'pending',   'B1-S2-A03 pending request'),
(@B1, @B1_C5, @B1_ST2, CONCAT(CURDATE(), ' 12:30:00'), 'cancelled', 'B1-S2-A04 cancelled today'),
(@B1, @B1_C1, @B1_ST2, CONCAT(CURDATE(), ' 13:30:00'), 'no_show',   'B1-S2-A05 no show today'),
(@B1, @B1_C2, @B1_ST2, CONCAT(DATE_SUB(CURDATE(), INTERVAL 1 DAY), ' 09:00:00'), 'completed', 'B1-S2-A06 completed -1d'),
(@B1, @B1_C3, @B1_ST2, CONCAT(DATE_SUB(CURDATE(), INTERVAL 5 DAY), ' 10:00:00'), 'completed', 'B1-S2-A07 completed -5d'),
(@B1, @B1_C4, @B1_ST2, CONCAT(DATE_SUB(CURDATE(), INTERVAL 20 DAY), ' 17:00:00'), 'rejected',  'B1-S2-A08 rejected -20d'),
(@B1, @B1_C5, @B1_ST2, CONCAT(DATE_ADD(CURDATE(), INTERVAL 1 DAY), ' 14:30:00'), 'scheduled', 'B1-S2-A09 scheduled +1d'),
(@B1, @B1_C1, @B1_ST2, CONCAT(DATE_ADD(CURDATE(), INTERVAL 6 DAY), ' 10:30:00'), 'pending',   'B1-S2-A10 pending +6d');

-- Staff 3 appointments (10)
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@B1, @B1_C3, @B1_ST3, CONCAT(CURDATE(), ' 09:15:00'), 'completed', 'B1-S3-A01 completed today'),
(@B1, @B1_C4, @B1_ST3, CONCAT(CURDATE(), ' 10:15:00'), 'scheduled', 'B1-S3-A02 scheduled today'),
(@B1, @B1_C5, @B1_ST3, CONCAT(CURDATE(), ' 11:15:00'), 'pending',   'B1-S3-A03 pending request'),
(@B1, @B1_C1, @B1_ST3, CONCAT(CURDATE(), ' 12:15:00'), 'cancelled', 'B1-S3-A04 cancelled today'),
(@B1, @B1_C2, @B1_ST3, CONCAT(CURDATE(), ' 13:15:00'), 'no_show',   'B1-S3-A05 no show today'),
(@B1, @B1_C3, @B1_ST3, CONCAT(DATE_SUB(CURDATE(), INTERVAL 3 DAY), ' 11:00:00'), 'completed', 'B1-S3-A06 completed -3d'),
(@B1, @B1_C4, @B1_ST3, CONCAT(DATE_SUB(CURDATE(), INTERVAL 8 DAY), ' 15:30:00'), 'completed', 'B1-S3-A07 completed -8d'),
(@B1, @B1_C5, @B1_ST3, CONCAT(DATE_SUB(CURDATE(), INTERVAL 30 DAY), ' 16:30:00'), 'rejected',  'B1-S3-A08 rejected -30d'),
(@B1, @B1_C1, @B1_ST3, CONCAT(DATE_ADD(CURDATE(), INTERVAL 4 DAY), ' 09:45:00'), 'scheduled', 'B1-S3-A09 scheduled +4d'),
(@B1, @B1_C2, @B1_ST3, CONCAT(DATE_ADD(CURDATE(), INTERVAL 12 DAY), ' 13:45:00'), 'pending',   'B1-S3-A10 pending +12d');

-- ------------------------------------------------------------
-- B1 appointment_services (mix of single/multiple services)
-- We'll reference appointments via notes tags.
-- ------------------------------------------------------------
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC1, 150.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A01 completed today';
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC3, 250.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A01 completed today';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC2, 900.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S2-A01 completed today';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC4, 400.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S3-A01 completed today';

-- scheduled examples
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC1, 150.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A02 scheduled today';
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC5, 120.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A02 scheduled today';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC3, 250.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S2-A02 scheduled today';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC2, 900.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S3-A02 scheduled today';

-- pending examples (multi-service)
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC1, 150.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A03 pending request';
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC4, 400.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A03 pending request';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC2, 900.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S2-A03 pending request';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC5, 120.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S3-A03 pending request';

-- add a few past completed combos
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC2, 900.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A08 completed -14d';
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC3, 250.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A08 completed -14d';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC1, 150.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S2-A06 completed -1d';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B1_SVC4, 400.00 FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S3-A06 completed -3d';

-- ------------------------------------------------------------
-- B1 transactions (mix: completed/pending/refunded, methods: cash/card/online)
-- Must satisfy unique_business_appointment_payment + optional idempotency key.
-- ------------------------------------------------------------
-- Completed transactions for completed appointments
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B1, a.id, a.customer_id, 400.00, 'cash', 'completed', CONCAT('b1_tx_', a.id, '_1'), CONCAT(DATE(a.appointment_date), ' 10:05:00')
FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A01 completed today';

INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B1, a.id, a.customer_id, 900.00, 'card', 'completed', CONCAT('b1_tx_', a.id, '_1'), CONCAT(DATE(a.appointment_date), ' 11:05:00')
FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S2-A01 completed today';

-- Refunded example (still unique due to different status)
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B1, a.id, a.customer_id, 900.00, 'card', 'refunded', CONCAT('b1_tx_', a.id, '_2'), CONCAT(DATE(a.appointment_date), ' 17:30:00')
FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S2-A01 completed today';

-- Pending payment example (for a scheduled appointment)
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B1, a.id, a.customer_id, 270.00, 'online', 'pending', CONCAT('b1_tx_', a.id, '_pre'), CONCAT(DATE(a.appointment_date), ' 10:10:00')
FROM appointments a WHERE a.business_id=@B1 AND a.notes='B1-S1-A02 scheduled today';

-- ============================================================
-- BUSINESS #2
-- ============================================================
INSERT INTO businesses (name, email, phone, address)
VALUES ('Wellness Clinic Ankara', 'b2@wellness.com', '05550000002', 'Ankara, Türkiye');

SET @B2 = LAST_INSERT_ID();

-- Users (1 owner + 2 admin + 1 staff user)
INSERT INTO users (business_id, email, password_hash, full_name, role) VALUES
(@B2, 'b2.owner@test.com', @PWD_HASH, 'B2 Owner', 'owner'),
(@B2, 'b2.admin1@test.com', @PWD_HASH, 'B2 Admin 1', 'admin'),
(@B2, 'b2.admin2@test.com', @PWD_HASH, 'B2 Admin 2', 'admin'),
(@B2, 'b2.staffuser1@test.com', @PWD_HASH, 'B2 StaffUser 1', 'staff');

SET @B2_OWNER  = (SELECT id FROM users WHERE business_id=@B2 AND email='b2.owner@test.com' LIMIT 1);
SET @B2_ADMIN1 = (SELECT id FROM users WHERE business_id=@B2 AND email='b2.admin1@test.com' LIMIT 1);
SET @B2_ADMIN2 = (SELECT id FROM users WHERE business_id=@B2 AND email='b2.admin2@test.com' LIMIT 1);
SET @B2_SU1    = (SELECT id FROM users WHERE business_id=@B2 AND email='b2.staffuser1@test.com' LIMIT 1);

-- Customers (5)
INSERT INTO customers (business_id, email, phone, full_name) VALUES
(@B2, 'b2.customer1@test.com', '05441111111', 'B2 Customer 1'),
(@B2, 'b2.customer2@test.com', '05442222222', 'B2 Customer 2'),
(@B2, 'b2.customer3@test.com', '05443333333', 'B2 Customer 3'),
(@B2, 'b2.customer4@test.com', '05444444444', 'B2 Customer 4'),
(@B2, 'b2.customer5@test.com', '05445555555', 'B2 Customer 5');

SET @B2_C1 = (SELECT id FROM customers WHERE business_id=@B2 AND email='b2.customer1@test.com' LIMIT 1);
SET @B2_C2 = (SELECT id FROM customers WHERE business_id=@B2 AND email='b2.customer2@test.com' LIMIT 1);
SET @B2_C3 = (SELECT id FROM customers WHERE business_id=@B2 AND email='b2.customer3@test.com' LIMIT 1);
SET @B2_C4 = (SELECT id FROM customers WHERE business_id=@B2 AND email='b2.customer4@test.com' LIMIT 1);
SET @B2_C5 = (SELECT id FROM customers WHERE business_id=@B2 AND email='b2.customer5@test.com' LIMIT 1);

-- Services (6, include 1 inactive)
INSERT INTO services (business_id, name, description, duration_minutes, price, is_active) VALUES
(@B2, 'Physio Session',     'Physical therapy session',  60, 600.00, 1),
(@B2, 'Massage',            'Relaxing massage',          45, 450.00, 1),
(@B2, 'Diet Consultation',  'Nutrition consult',         30, 350.00, 1),
(@B2, 'Skin Care',          'Facial skin care',          50, 500.00, 1),
(@B2, 'Laser Session',      'Laser application',         40, 800.00, 1),
(@B2, 'Inactive Service Y', 'Deprecated service',        30, 120.00, 0);

SET @B2_SVC1 = (SELECT id FROM services WHERE business_id=@B2 AND name='Physio Session' LIMIT 1);
SET @B2_SVC2 = (SELECT id FROM services WHERE business_id=@B2 AND name='Massage' LIMIT 1);
SET @B2_SVC3 = (SELECT id FROM services WHERE business_id=@B2 AND name='Diet Consultation' LIMIT 1);
SET @B2_SVC4 = (SELECT id FROM services WHERE business_id=@B2 AND name='Skin Care' LIMIT 1);
SET @B2_SVC5 = (SELECT id FROM services WHERE business_id=@B2 AND name='Laser Session' LIMIT 1);
SET @B2_SVC6 = (SELECT id FROM services WHERE business_id=@B2 AND name='Inactive Service Y' LIMIT 1);

-- Staff (3) - again 2 linked to users, 1 without panel
INSERT INTO staff (business_id, user_id, full_name, email, phone, is_active) VALUES
(@B2, @B2_SU1,    'B2 Staff 1', 'b2.staff1@test.com', '05446660001', 1),
(@B2, @B2_ADMIN2, 'B2 Staff 2 (Admin)', 'b2.staff2@test.com', '05446660002', 1),
(@B2, NULL,       'B2 Staff 3 (No Panel)', 'b2.staff3@test.com', '05446660003', 1);

SET @B2_ST1 = (SELECT id FROM staff WHERE business_id=@B2 AND email='b2.staff1@test.com' LIMIT 1);
SET @B2_ST2 = (SELECT id FROM staff WHERE business_id=@B2 AND email='b2.staff2@test.com' LIMIT 1);
SET @B2_ST3 = (SELECT id FROM staff WHERE business_id=@B2 AND email='b2.staff3@test.com' LIMIT 1);

-- Business settings (different values)
INSERT INTO business_settings (business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours, working_hours_start, working_hours_end, timezone)
VALUES (@B2, 20, 10, 12, '08:30:00', '18:30:00', 'Europe/Istanbul');

-- Staff day locks
INSERT INTO staff_day_locks (business_id, staff_id, day_date) VALUES
(@B2, @B2_ST1, DATE_ADD(CURDATE(), INTERVAL 1 DAY)),
(@B2, @B2_ST2, DATE_ADD(CURDATE(), INTERVAL 7 DAY)),
(@B2, @B2_ST3, DATE_SUB(CURDATE(), INTERVAL 15 DAY));

-- Booking links (3)
INSERT INTO booking_links (business_id, token, name, description, service_ids, staff_ids, start_date, end_date, max_uses, current_uses, is_active)
VALUES
(@B2, 'b2_token_all_001', 'B2 - General Booking Link', 'All staff & services', NULL, NULL,
 DATE_SUB(CURDATE(), INTERVAL 10 DAY), DATE_ADD(CURDATE(), INTERVAL 90 DAY), NULL, 1, 1);

INSERT INTO booking_links (business_id, token, name, description, service_ids, staff_ids, start_date, end_date, max_uses, current_uses, is_active)
VALUES
(@B2, 'b2_token_physio_001', 'B2 - Physio Only', 'Physio + Massage, Staff1 only', JSON_ARRAY(@B2_SVC1, @B2_SVC2), JSON_ARRAY(@B2_ST1),
 DATE_SUB(CURDATE(), INTERVAL 3 DAY), DATE_ADD(CURDATE(), INTERVAL 30 DAY), 20, 4, 1);

INSERT INTO booking_links (business_id, token, name, description, service_ids, staff_ids, start_date, end_date, max_uses, current_uses, is_active)
VALUES
(@B2, 'b2_token_inactive_001', 'B2 - Inactive Link', 'Inactive example', JSON_ARRAY(@B2_SVC5), JSON_ARRAY(@B2_ST2, @B2_ST3),
 NULL, NULL, NULL, 0, 0);

-- ------------------------------------------------------------
-- B2 APPOINTMENTS (3 staff x 10 = 30)
-- ------------------------------------------------------------

-- Staff 1
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@B2, @B2_C1, @B2_ST1, CONCAT(CURDATE(), ' 08:30:00'), 'completed', 'B2-S1-A01 completed today'),
(@B2, @B2_C2, @B2_ST1, CONCAT(CURDATE(), ' 09:10:00'), 'scheduled', 'B2-S1-A02 scheduled today'),
(@B2, @B2_C3, @B2_ST1, CONCAT(CURDATE(), ' 09:50:00'), 'pending',   'B2-S1-A03 pending request'),
(@B2, @B2_C4, @B2_ST1, CONCAT(CURDATE(), ' 10:30:00'), 'cancelled', 'B2-S1-A04 cancelled today'),
(@B2, @B2_C5, @B2_ST1, CONCAT(CURDATE(), ' 11:10:00'), 'no_show',   'B2-S1-A05 no show today'),
(@B2, @B2_C1, @B2_ST1, CONCAT(DATE_SUB(CURDATE(), INTERVAL 4 DAY), ' 13:00:00'), 'completed', 'B2-S1-A06 completed -4d'),
(@B2, @B2_C2, @B2_ST1, CONCAT(DATE_SUB(CURDATE(), INTERVAL 9 DAY), ' 15:20:00'), 'completed', 'B2-S1-A07 completed -9d'),
(@B2, @B2_C3, @B2_ST1, CONCAT(DATE_SUB(CURDATE(), INTERVAL 21 DAY), ' 16:10:00'), 'rejected',  'B2-S1-A08 rejected -21d'),
(@B2, @B2_C4, @B2_ST1, CONCAT(DATE_ADD(CURDATE(), INTERVAL 2 DAY), ' 12:30:00'), 'scheduled', 'B2-S1-A09 scheduled +2d'),
(@B2, @B2_C5, @B2_ST1, CONCAT(DATE_ADD(CURDATE(), INTERVAL 8 DAY), ' 14:10:00'), 'pending',   'B2-S1-A10 pending +8d');

-- Staff 2
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@B2, @B2_C2, @B2_ST2, CONCAT(CURDATE(), ' 08:45:00'), 'completed', 'B2-S2-A01 completed today'),
(@B2, @B2_C3, @B2_ST2, CONCAT(CURDATE(), ' 09:25:00'), 'scheduled', 'B2-S2-A02 scheduled today'),
(@B2, @B2_C4, @B2_ST2, CONCAT(CURDATE(), ' 10:05:00'), 'pending',   'B2-S2-A03 pending request'),
(@B2, @B2_C5, @B2_ST2, CONCAT(CURDATE(), ' 10:45:00'), 'cancelled', 'B2-S2-A04 cancelled today'),
(@B2, @B2_C1, @B2_ST2, CONCAT(CURDATE(), ' 11:25:00'), 'no_show',   'B2-S2-A05 no show today'),
(@B2, @B2_C2, @B2_ST2, CONCAT(DATE_SUB(CURDATE(), INTERVAL 2 DAY), ' 09:40:00'), 'completed', 'B2-S2-A06 completed -2d'),
(@B2, @B2_C3, @B2_ST2, CONCAT(DATE_SUB(CURDATE(), INTERVAL 12 DAY), ' 10:20:00'), 'completed', 'B2-S2-A07 completed -12d'),
(@B2, @B2_C4, @B2_ST2, CONCAT(DATE_SUB(CURDATE(), INTERVAL 33 DAY), ' 17:10:00'), 'rejected',  'B2-S2-A08 rejected -33d'),
(@B2, @B2_C5, @B2_ST2, CONCAT(DATE_ADD(CURDATE(), INTERVAL 5 DAY), ' 13:30:00'), 'scheduled', 'B2-S2-A09 scheduled +5d'),
(@B2, @B2_C1, @B2_ST2, CONCAT(DATE_ADD(CURDATE(), INTERVAL 11 DAY), ' 16:30:00'), 'pending',   'B2-S2-A10 pending +11d');

-- Staff 3
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@B2, @B2_C3, @B2_ST3, CONCAT(CURDATE(), ' 08:55:00'), 'completed', 'B2-S3-A01 completed today'),
(@B2, @B2_C4, @B2_ST3, CONCAT(CURDATE(), ' 09:35:00'), 'scheduled', 'B2-S3-A02 scheduled today'),
(@B2, @B2_C5, @B2_ST3, CONCAT(CURDATE(), ' 10:15:00'), 'pending',   'B2-S3-A03 pending request'),
(@B2, @B2_C1, @B2_ST3, CONCAT(CURDATE(), ' 10:55:00'), 'cancelled', 'B2-S3-A04 cancelled today'),
(@B2, @B2_C2, @B2_ST3, CONCAT(CURDATE(), ' 11:35:00'), 'no_show',   'B2-S3-A05 no show today'),
(@B2, @B2_C3, @B2_ST3, CONCAT(DATE_SUB(CURDATE(), INTERVAL 6 DAY), ' 14:20:00'), 'completed', 'B2-S3-A06 completed -6d'),
(@B2, @B2_C4, @B2_ST3, CONCAT(DATE_SUB(CURDATE(), INTERVAL 18 DAY), ' 15:40:00'), 'completed', 'B2-S3-A07 completed -18d'),
(@B2, @B2_C5, @B2_ST3, CONCAT(DATE_SUB(CURDATE(), INTERVAL 45 DAY), ' 16:50:00'), 'rejected',  'B2-S3-A08 rejected -45d'),
(@B2, @B2_C1, @B2_ST3, CONCAT(DATE_ADD(CURDATE(), INTERVAL 4 DAY), ' 12:10:00'), 'scheduled', 'B2-S3-A09 scheduled +4d'),
(@B2, @B2_C2, @B2_ST3, CONCAT(DATE_ADD(CURDATE(), INTERVAL 15 DAY), ' 14:50:00'), 'pending',   'B2-S3-A10 pending +15d');

-- B2 appointment_services
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B2_SVC1, 600.00 FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S1-A01 completed today';
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B2_SVC2, 450.00 FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S1-A01 completed today';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B2_SVC4, 500.00 FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S2-A01 completed today';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B2_SVC5, 800.00 FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S3-A01 completed today';

-- pending / scheduled examples
INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B2_SVC3, 350.00 FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S1-A03 pending request';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B2_SVC2, 450.00 FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S2-A02 scheduled today';

INSERT INTO appointment_services (appointment_id, service_id, price)
SELECT a.id, @B2_SVC1, 600.00 FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S3-A02 scheduled today';

-- B2 transactions
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B2, a.id, a.customer_id, 1050.00, 'online', 'completed', CONCAT('b2_tx_', a.id, '_1'), CONCAT(DATE(a.appointment_date), ' 09:20:00')
FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S1-A01 completed today';

INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B2, a.id, a.customer_id, 500.00, 'cash', 'completed', CONCAT('b2_tx_', a.id, '_1'), CONCAT(DATE(a.appointment_date), ' 10:10:00')
FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S2-A01 completed today';

-- refunded
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B2, a.id, a.customer_id, 500.00, 'cash', 'refunded', CONCAT('b2_tx_', a.id, '_2'), CONCAT(DATE(a.appointment_date), ' 18:00:00')
FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S2-A01 completed today';

-- prepayment pending for scheduled
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key, transaction_date)
SELECT @B2, a.id, a.customer_id, 450.00, 'card', 'pending', CONCAT('b2_tx_', a.id, '_pre'), CONCAT(DATE(a.appointment_date), ' 09:30:00')
FROM appointments a WHERE a.business_id=@B2 AND a.notes='B2-S2-A02 scheduled today';

-- ------------------------------------------------------------
-- Done
-- ------------------------------------------------------------
