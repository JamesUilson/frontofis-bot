# 🪪 A'zolik guvohnomasi — qo'llanma

Botga qo'shilgan yangi bo'lim. Guvohnoma **faqat admin yuklagan ro'yxatdagi**
shaxslarga beriladi.

---

## 1. Admin: a'zolar ro'yxatini yuklash

`/admin` → **🪪 A'zolik guvohnomasi**

| Tugma | Vazifasi |
|---|---|
| 📄 Excel namuna | To'ldirish uchun tayyor shablon yuboradi |
| 📥 Ro'yxatni yuklash | `.xlsx` faylni qabul qilib ro'yxatga qo'shadi |
| 📊 Ro'yxat (Excel) | Hozirgi tasdiqlangan a'zolar ro'yxati |
| 🪪 Berilganlar (Excel) | Berilgan barcha guvohnomalar hisoboti |
| 🗑 Ro'yxatni tozalash | Ro'yxatni o'chiradi (faqat superadmin) |

### Excel ustunlari

| Familiyasi | Ismi | Otasining ismi | ID raqami (4 xona) | Telegram ID | Telefon | Hudud | Lavozim |
|---|---|---|---|---|---|---|---|
| Bahodirov | Baxtiyorjon | Abdulaziz o'g'li | 0125 | 2110945697 | +998901234567 | Toshkent shahri | |
| Karimova | Nilufar | Akmal qizi | | | +998935556677 | Farg'ona | |

* **Telegram ID** yoki **Telefon** — kamida bittasi bo'lishi shart. Bot
  foydalanuvchini avval Telegram ID, topilmasa telefon raqami bo'yicha qidiradi.
* **Hudud** ID raqamining birinchi 2 raqamini belgilaydi. Yozilishi erkin —
  `Farg'ona`, `Fargona viloyati`, `FARGONA` hammasi tanib olinadi.
* **ID raqami (4 xona)** — guvohnoma ID sining oxirgi 4 raqami:
  * **To'ldirilsa** — aynan shu raqam beriladi: `01` + `0125` = **010125**
  * **Bo'sh qoldirilsa** — **Telegram ID sining oxirgi 4 raqami** olinadi
    (`2110945697` → `5697` → **015697**)
  * `125` deb yozilsa `0125` ga, to'liq `010125` yozilsa oxirgi 4 xonasiga
    keltiriladi
  * Telegram ID ham bo'lmasa — guvohnoma berilayotgan paytda foydalanuvchining
    haqiqiy Telegram ID sidan olinadi, u ham band bo'lsa tasodifiy raqam
* **Lavozim** bo'sh bo'lsa avtomatik `<Hudud> koordinatori` yoziladi.
* Faylni qayta yuklasa **dublikat yaratilmaydi** — mavjud yozuv yangilanadi.

### Takroriy ID

ID raqami band bo'lsa **o'sha qator yuklanmaydi** va admin hisobotda sababini
ko'radi. Uch xil holat tekshiriladi:

| Holat | Xabar |
|---|---|
| Fayl ichida ikki qatorda bir xil ID | `fayl ichida N-qator bilan bir xil` |
| Guvohnoma allaqachon berilgan | `guvohnoma allaqachon berilgan: <F.I>` |
| Ro'yxatdagi boshqa a'zoga band | `ro'yxatda band: <F.I>` |

Excel'da tuzatib faylni qayta yuklash kifoya — qolgan qatorlar birinchi
yuklashda allaqachon saqlangan bo'ladi.

> ID **hudud bilan birga** tekshiriladi: `0999` raqami Toshkentda ham,
> Andijonda ham bo'lishi mumkin (`010999` va `030999` — turli ID lar).
> Hudud tanilmagan qatorda ID saqlanadi, lekin to'liq ID foydalanuvchi
> hududni tanlaganda shakllanadi.

---

## 2. Foydalanuvchi

Asosiy menyu → **🪪 A'zolik guvohnomasi**

1. Ro'yxatdan topilsa — darhol davom etadi. Topilmasa telefon raqami so'raladi.
2. Ro'yxatda umuman bo'lmasa — rad javobi beriladi.
3. Excel'da yetishmagan ma'lumot (familiya / ism / otasining ismi / hudud)
   botning o'zi so'raydi.
4. **3x4 rasm** — front ofis arizasida yuborgan rasmi avtomatik olinadi,
   bo'lmasa so'raladi.
5. Guvohnomaning **old va orqa tomoni** rasm ko'rinishida yuboriladi.
   «🖨 Chop etish uchun» tugmasi siqilmagan PNG fayllarni beradi.

Bir foydalanuvchiga bitta guvohnoma. Qayta bosganda o'sha guvohnoma qayta yuboriladi.

---

## 3. ID raqami

```
01  0125
└┬┘ └─┬┘
 │    └── Excel'dagi «ID raqami» ustuni → bo'sh bo'lsa Telegram ID
 │        oxirgi 4 raqami → u ham band bo'lsa tasodifiy raqam
 └─────── hudud kodi (Hudud ustunidan avtomatik)
```

**Seriya raqami** (orqa tomon) = ID raqamining oxirgi 4 raqami.

| Kod | Hudud | Kod | Hudud |
|---|---|---|---|
| 01 | Toshkent shahri | 08 | Xorazm |
| 02 | Toshkent viloyati | 09 | Surxondaryo |
| 03 | Andijon | 10 | Qashqadaryo |
| 04 | Farg'ona | 11 | Jizzax |
| 05 | Namangan | 12 | Sirdaryo |
| 06 | Samarqand | 13 | Navoiy |
| 07 | Buxoro | 14 | Qoraqalpog'iston Respublikasi |

---

## 4. Sanalar va QR kod

* **Berilgan sanasi** — guvohnoma olingan kun (avtomatik).
* **Amal qilish muddati** — `31.08.2027`, o'zgarmaydi
  (`GUV_EXPIRE_DATE` orqali sozlanadi).
* **QR kod** — `https://t.me/FrontOfisBot?start=guv_<ID>` manziliga olib boradi
  va guvohnoma egasining ma'lumotlarini ko'rsatib **haqiqiyligini tasdiqlaydi**.
  Soxta yoki mavjud bo'lmagan ID kiritilsa — «haqiqiy emas» ogohlantirishi chiqadi.
* QR kodsiz ham tekshirish mumkin: **🔍 Sertifikat tekshirish** bo'limiga
  6 xonali ID raqamni kiritish kifoya.

---

## 5. Texnik ma'lumot

| Fayl | Izoh |
|---|---|
| `certificates/guvohnoma_old.png` | Old tomon shabloni (2024×1276 px, 600 dpi) |
| `certificates/guvohnoma_orqa.png` | Orqa tomon shabloni |
| `certificates/fonts/Lato-*.ttf` | Shrift (namunadagi shriftga eng yaqin, OFL litsenziya) |

Karta o'lchami **85.6 × 54 mm** — xalqaro ID-1 standarti, plastik kartaga
to'g'ridan-to'g'ri chop etish mumkin.

Yangi jadvallar bot birinchi marta ishga tushganda avtomatik yaratiladi:
`approved_members` (ro'yxat) va `membership_cards` (berilgan guvohnomalar).
`approved_members.card_no` ustuni mavjud bazaga avtomatik qo'shiladi
(migratsiya) — eski ma'lumotlar saqlanib qoladi.

Kerakli kutubxonalar: `pillow`, `qrcode`, `openpyxl` (mavjud edi).
