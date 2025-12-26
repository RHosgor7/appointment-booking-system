# GitHub'a Push Etme Adımları

## ✅ Tamamlanan İşlemler

- ✅ Git repository başlatıldı
- ✅ 344 dosya commit edildi
- ✅ Branch: master (main olarak değiştirilebilir)

## 🚀 GitHub'a Yükleme

### 1. GitHub'da Repository Oluşturun

1. https://github.com adresine gidin
2. Sağ üstteki **"+"** butonuna tıklayın
3. **"New repository"** seçin
4. Repository bilgilerini doldurun:
   - **Name**: `appointment-booking-system` (veya istediğiniz isim)
   - **Description**: "Multi-tenant appointment booking system with FastAPI"
   - **Visibility**: Private (önerilen) veya Public
   - ⚠️ **"Initialize with README"** seçeneğini **İŞARETLEMEYİN** (zaten README.md var)
5. **"Create repository"** butonuna tıklayın

### 2. Remote Repository Ekleyin

Terminal'de demo klasöründe şu komutu çalıştırın:

```bash
cd /Users/ramazahosgor/Desktop/2025-2026-Güz/BLG317/project/demo

# HTTPS kullanıyorsanız (önerilen):
git remote add origin https://github.com/YOUR_USERNAME/appointment-booking-system.git

# VEYA SSH kullanıyorsanız:
# git remote add origin git@github.com:YOUR_USERNAME/appointment-booking-system.git
```

**Not**: `YOUR_USERNAME` ve `appointment-booking-system` kısımlarını kendi bilgilerinizle değiştirin.

### 3. Branch'i Main Olarak Değiştirin (Opsiyonel)

```bash
git branch -M main
```

### 4. GitHub'a Push Edin

```bash
# İlk push
git push -u origin main

# VEYA master branch kullanıyorsanız:
# git push -u origin master
```

### 5. Authentication

Eğer authentication sorunu yaşarsanız:

#### A) Personal Access Token (HTTPS için)

1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. "Generate new token" → "Generate new token (classic)"
3. İsim verin (örn: "appointment-booking")
4. `repo` scope'unu seçin
5. "Generate token" butonuna tıklayın
6. Token'ı kopyalayın (bir daha gösterilmeyecek!)
7. Push yaparken password yerine bu token'ı kullanın

#### B) SSH Key (Önerilen)

```bash
# SSH key oluştur (eğer yoksa)
ssh-keygen -t ed25519 -C "your.email@example.com"

# Public key'i göster
cat ~/.ssh/id_ed25519.pub

# Bu key'i kopyalayın ve GitHub'a ekleyin:
# GitHub → Settings → SSH and GPG keys → New SSH key

# Remote URL'i SSH olarak değiştirin:
git remote set-url origin git@github.com:YOUR_USERNAME/appointment-booking-system.git

# Tekrar push edin
git push -u origin main
```

## ✅ Kontrol

Push işlemi başarılı olduktan sonra:

1. GitHub repository sayfanızı açın
2. Tüm dosyaların yüklendiğini kontrol edin
3. README.md dosyasının göründüğünü doğrulayın

## 📝 Sonraki Adımlar

1. **Repository Ayarları**:
   - Description ekleyin
   - Topics ekleyin: `fastapi`, `python`, `mysql`, `appointment-booking`, `multi-tenant`

2. **README.md Güncelleme**:
   - `demo/README.md` dosyasını kontrol edin
   - Gerekirse güncelleyin

3. **.env Dosyası**:
   - `.env` dosyası `.gitignore`'da olduğu için yüklenmeyecek (güvenlik için doğru)
   - `.env.example` dosyası yüklenecek

## 🔄 Gelecekteki Güncellemeler

Değişiklik yaptıktan sonra:

```bash
cd /Users/ramazahosgor/Desktop/2025-2026-Güz/BLG317/project/demo

# Değişiklikleri kontrol et
git status

# Değişiklikleri ekle
git add .

# Commit yap
git commit -m "Description of changes"

# Push et
git push
```

## ⚠️ Önemli Notlar

- `.env` dosyası yüklenmeyecek (güvenlik için)
- `venv/` klasörü yüklenmeyecek (`.gitignore`'da)
- `__pycache__/` dosyaları yüklenmeyecek

## 🆘 Sorun Giderme

### "remote origin already exists" hatası:
```bash
git remote remove origin
git remote add origin https://github.com/YOUR_USERNAME/appointment-booking-system.git
```

### "Permission denied" hatası:
- Personal Access Token kullanın veya SSH key ekleyin

### "Branch 'main' does not exist" hatası:
```bash
git branch -M main
# veya
git push -u origin master
```

