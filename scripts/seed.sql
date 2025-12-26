-- Seed Data - Test için örnek veri
-- Password: test123 (bcrypt hash: $2b$12$bhhxMO1y1eEgiTadJPaD4e5jxN5GfWoQYn6Ney1UiXL2cHSrh24te)

-- 1 business
INSERT INTO businesses (name, email, phone, address) VALUES
('Test Salon', 'test@salon.com', '05551234567', 'İstanbul, Türkiye');

SET @business_id = LAST_INSERT_ID();

-- 2 users (1 owner, 1 staff)
-- Password: test123
INSERT INTO users (business_id, email, password_hash, full_name, role) VALUES
(@business_id, 'owner@test.com', '$2b$12$bhhxMO1y1eEgiTadJPaD4e5jxN5GfWoQYn6Ney1UiXL2cHSrh24te', 'Test Owner', 'owner'),
(@business_id, 'staff@test.com', '$2b$12$bhhxMO1y1eEgiTadJPaD4e5jxN5GfWoQYn6Ney1UiXL2cHSrh24te', 'Test Staff', 'staff');

SET @owner_user_id = (SELECT id FROM users WHERE email = 'owner@test.com' AND business_id = @business_id LIMIT 1);
SET @staff_user_id = (SELECT id FROM users WHERE email = 'staff@test.com' AND business_id = @business_id LIMIT 1);

-- 5 customers
INSERT INTO customers (business_id, email, phone, full_name) VALUES
(@business_id, 'customer1@test.com', '05551111111', 'Müşteri 1'),
(@business_id, 'customer2@test.com', '05552222222', 'Müşteri 2'),
(@business_id, 'customer3@test.com', '05553333333', 'Müşteri 3'),
(@business_id, 'customer4@test.com', '05554444444', 'Müşteri 4'),
(@business_id, 'customer5@test.com', '05555555555', 'Müşteri 5');

SET @customer1_id = (SELECT id FROM customers WHERE email = 'customer1@test.com' AND business_id = @business_id LIMIT 1);
SET @customer2_id = (SELECT id FROM customers WHERE email = 'customer2@test.com' AND business_id = @business_id LIMIT 1);
SET @customer3_id = (SELECT id FROM customers WHERE email = 'customer3@test.com' AND business_id = @business_id LIMIT 1);
SET @customer4_id = (SELECT id FROM customers WHERE email = 'customer4@test.com' AND business_id = @business_id LIMIT 1);
SET @customer5_id = (SELECT id FROM customers WHERE email = 'customer5@test.com' AND business_id = @business_id LIMIT 1);

-- 5 services (farklı fiyat ve sürelerle)
INSERT INTO services (business_id, name, description, duration_minutes, price, is_active) VALUES
(@business_id, 'Saç Kesimi', 'Klasik saç kesimi', 30, 100.00, 1),
(@business_id, 'Saç Boyama', 'Tam boyama', 120, 500.00, 1),
(@business_id, 'Fön', 'Saç şekillendirme', 45, 150.00, 1),
(@business_id, 'Saç Bakımı', 'Derin bakım', 60, 200.00, 1),
(@business_id, 'Sakal Tıraşı', 'Klasik tıraş', 20, 80.00, 1);

SET @service1_id = (SELECT id FROM services WHERE name = 'Saç Kesimi' AND business_id = @business_id LIMIT 1);
SET @service2_id = (SELECT id FROM services WHERE name = 'Saç Boyama' AND business_id = @business_id LIMIT 1);
SET @service3_id = (SELECT id FROM services WHERE name = 'Fön' AND business_id = @business_id LIMIT 1);
SET @service4_id = (SELECT id FROM services WHERE name = 'Saç Bakımı' AND business_id = @business_id LIMIT 1);
SET @service5_id = (SELECT id FROM services WHERE name = 'Sakal Tıraşı' AND business_id = @business_id LIMIT 1);

-- 2 staff (1 tanesi user'a bağlı)
INSERT INTO staff (business_id, user_id, full_name, email, phone, is_active) VALUES
(@business_id, @staff_user_id, 'Personel 1', 'staff1@test.com', '05553333333', 1),
(@business_id, NULL, 'Personel 2', 'staff2@test.com', '05554444444', 1);

SET @staff1_id = (SELECT id FROM staff WHERE email = 'staff1@test.com' AND business_id = @business_id LIMIT 1);
SET @staff2_id = (SELECT id FROM staff WHERE email = 'staff2@test.com' AND business_id = @business_id LIMIT 1);

-- business_settings
INSERT INTO business_settings (business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours) VALUES
(@business_id, 30, 15, 24);

-- Bugünün randevuları (farklı status'lerle)
-- Scheduled randevular (yaklaşan randevular için)
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@business_id, @customer1_id, @staff1_id, CONCAT(CURDATE(), ' 10:00:00'), 'scheduled', 'İlk randevu'),
(@business_id, @customer2_id, @staff1_id, CONCAT(CURDATE(), ' 11:30:00'), 'scheduled', 'Kontrol randevusu'),
(@business_id, @customer3_id, @staff2_id, CONCAT(CURDATE(), ' 14:00:00'), 'scheduled', NULL);

-- Bugünün completed randevuları
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@business_id, @customer4_id, @staff1_id, CONCAT(CURDATE(), ' 09:00:00'), 'completed', 'Tamamlandı'),
(@business_id, @customer5_id, @staff2_id, CONCAT(CURDATE(), ' 13:00:00'), 'completed', 'Başarılı');

-- Bugünün cancelled randevuları
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@business_id, @customer1_id, @staff2_id, CONCAT(CURDATE(), ' 15:00:00'), 'cancelled', 'Müşteri iptal etti');

-- Son 7 günün randevuları (performans widget için)
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@business_id, @customer2_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 1 DAY), 'completed', 'Dün tamamlandı'),
(@business_id, @customer3_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 2 DAY), 'completed', '2 gün önce'),
(@business_id, @customer4_id, @staff2_id, DATE_SUB(CURDATE(), INTERVAL 3 DAY), 'completed', '3 gün önce'),
(@business_id, @customer5_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 4 DAY), 'cancelled', '4 gün önce iptal'),
(@business_id, @customer1_id, @staff2_id, DATE_SUB(CURDATE(), INTERVAL 5 DAY), 'completed', '5 gün önce'),
(@business_id, @customer2_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 6 DAY), 'completed', '6 gün önce');

-- Bu ayın randevuları (MTD için)
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@business_id, @customer3_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 10 DAY), 'completed', '10 gün önce'),
(@business_id, @customer4_id, @staff2_id, DATE_SUB(CURDATE(), INTERVAL 15 DAY), 'completed', '15 gün önce'),
(@business_id, @customer5_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 20 DAY), 'cancelled', '20 gün önce iptal'),
(@business_id, @customer1_id, @staff2_id, DATE_SUB(CURDATE(), INTERVAL 25 DAY), 'completed', '25 gün önce');

-- Son 30 günün randevuları
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@business_id, @customer2_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 12 DAY), 'completed', '12 gün önce'),
(@business_id, @customer3_id, @staff2_id, DATE_SUB(CURDATE(), INTERVAL 18 DAY), 'completed', '18 gün önce'),
(@business_id, @customer4_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 22 DAY), 'completed', '22 gün önce');

-- Appointment services (randevulara hizmetler ekle)
-- Bugünün scheduled randevuları
SET @appt_today_1 = (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = CURDATE() AND status = 'scheduled' ORDER BY appointment_date LIMIT 1);
SET @appt_today_2 = (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = CURDATE() AND status = 'scheduled' ORDER BY appointment_date LIMIT 1 OFFSET 1);
SET @appt_today_3 = (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = CURDATE() AND status = 'scheduled' ORDER BY appointment_date LIMIT 1 OFFSET 2);

-- Bugünün completed randevuları
SET @appt_today_completed_1 = (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = CURDATE() AND status = 'completed' ORDER BY appointment_date LIMIT 1);
SET @appt_today_completed_2 = (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = CURDATE() AND status = 'completed' ORDER BY appointment_date LIMIT 1 OFFSET 1);

-- Appointment services ekle
INSERT INTO appointment_services (appointment_id, service_id, price) VALUES
-- Bugünün scheduled randevuları
(@appt_today_1, @service1_id, 100.00),
(@appt_today_1, @service3_id, 150.00),
(@appt_today_2, @service2_id, 500.00),
(@appt_today_3, @service4_id, 200.00),
-- Bugünün completed randevuları
(@appt_today_completed_1, @service1_id, 100.00),
(@appt_today_completed_2, @service5_id, 80.00),
-- Geçmiş randevular (farklı servis kombinasyonları)
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY) LIMIT 1), @service2_id, 500.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 2 DAY) LIMIT 1), @service1_id, 100.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 2 DAY) LIMIT 1), @service3_id, 150.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 3 DAY) LIMIT 1), @service4_id, 200.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 4 DAY) LIMIT 1), @service1_id, 100.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 5 DAY) LIMIT 1), @service5_id, 80.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 6 DAY) LIMIT 1), @service2_id, 500.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 10 DAY) LIMIT 1), @service3_id, 150.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 15 DAY) LIMIT 1), @service1_id, 100.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 20 DAY) LIMIT 1), @service2_id, 500.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 25 DAY) LIMIT 1), @service4_id, 200.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 12 DAY) LIMIT 1), @service5_id, 80.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 18 DAY) LIMIT 1), @service1_id, 100.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 22 DAY) LIMIT 1), @service3_id, 150.00);

-- Transactions (completed randevular için)
-- Bugünün completed randevuları için transaction'lar
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, transaction_date) VALUES
(@business_id, @appt_today_completed_1, @customer4_id, 100.00, 'cash', 'completed', CONCAT(CURDATE(), ' 09:30:00')),
(@business_id, @appt_today_completed_2, @customer5_id, 80.00, 'card', 'completed', CONCAT(CURDATE(), ' 13:30:00'));

-- Geçmiş randevular için transaction'lar (farklı tarihlerde)
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, transaction_date) VALUES
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY) LIMIT 1), @customer2_id, 500.00, 'card', 'completed', DATE_SUB(CURDATE(), INTERVAL 1 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 2 DAY) LIMIT 1), @customer3_id, 250.00, 'cash', 'completed', DATE_SUB(CURDATE(), INTERVAL 2 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 3 DAY) LIMIT 1), @customer4_id, 200.00, 'online', 'completed', DATE_SUB(CURDATE(), INTERVAL 3 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 5 DAY) LIMIT 1), @customer1_id, 80.00, 'cash', 'completed', DATE_SUB(CURDATE(), INTERVAL 5 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 6 DAY) LIMIT 1), @customer2_id, 500.00, 'card', 'completed', DATE_SUB(CURDATE(), INTERVAL 6 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 10 DAY) LIMIT 1), @customer3_id, 150.00, 'cash', 'completed', DATE_SUB(CURDATE(), INTERVAL 10 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 15 DAY) LIMIT 1), @customer4_id, 100.00, 'card', 'completed', DATE_SUB(CURDATE(), INTERVAL 15 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 25 DAY) LIMIT 1), @customer1_id, 200.00, 'online', 'completed', DATE_SUB(CURDATE(), INTERVAL 25 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 12 DAY) LIMIT 1), @customer2_id, 80.00, 'cash', 'completed', DATE_SUB(CURDATE(), INTERVAL 12 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 18 DAY) LIMIT 1), @customer3_id, 100.00, 'card', 'completed', DATE_SUB(CURDATE(), INTERVAL 18 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 22 DAY) LIMIT 1), @customer4_id, 150.00, 'cash', 'completed', DATE_SUB(CURDATE(), INTERVAL 22 DAY));

-- Önceki dönem için transaction'lar (trend hesaplama için - 31-60 gün önce)
INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes) VALUES
(@business_id, @customer1_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 35 DAY), 'completed', '35 gün önce'),
(@business_id, @customer2_id, @staff2_id, DATE_SUB(CURDATE(), INTERVAL 40 DAY), 'completed', '40 gün önce'),
(@business_id, @customer3_id, @staff1_id, DATE_SUB(CURDATE(), INTERVAL 45 DAY), 'completed', '45 gün önce'),
(@business_id, @customer4_id, @staff2_id, DATE_SUB(CURDATE(), INTERVAL 50 DAY), 'completed', '50 gün önce');

-- Önceki dönem appointment services
INSERT INTO appointment_services (appointment_id, service_id, price) VALUES
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 35 DAY) LIMIT 1), @service1_id, 100.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 40 DAY) LIMIT 1), @service2_id, 500.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 45 DAY) LIMIT 1), @service3_id, 150.00),
((SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 50 DAY) LIMIT 1), @service4_id, 200.00);

-- Önceki dönem transactions
INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, transaction_date) VALUES
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 35 DAY) LIMIT 1), @customer1_id, 100.00, 'cash', 'completed', DATE_SUB(CURDATE(), INTERVAL 35 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 40 DAY) LIMIT 1), @customer2_id, 500.00, 'card', 'completed', DATE_SUB(CURDATE(), INTERVAL 40 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 45 DAY) LIMIT 1), @customer3_id, 150.00, 'cash', 'completed', DATE_SUB(CURDATE(), INTERVAL 45 DAY)),
(@business_id, (SELECT id FROM appointments WHERE business_id = @business_id AND DATE(appointment_date) = DATE_SUB(CURDATE(), INTERVAL 50 DAY) LIMIT 1), @customer4_id, 200.00, 'online', 'completed', DATE_SUB(CURDATE(), INTERVAL 50 DAY));
