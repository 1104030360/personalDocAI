# Phase 29：實體與待辦資料層（design3.md D12／D13 的地基）

> 🎯 **對外行為零改變**：本 phase 只加表與 repository 函式，端點、回應、前端都不動。
> 資料庫遷移「一次改到位」：四張新表一支腳本建齊（正式庫只動一次），程式仍 phase 一次一項。

**目標：** 建 `entity`（實體＝別針，名稱唯一）、`photo_entity`（多對多連結）、`task`（待辦，每張照片 0..1 筆）、`folder_correction`（P35 few-shot 用，先建表不寫程式）四張表；entity 的 repository 五函式；測試安全網同步擴充。

## 檔案

- 改：`db/schema.sql`（四張新表＋DROP 順序）
- 建：`db/migrate_design3.sql`（可重跑；正式庫遷移用）
- 改：`app/repositories/photo_repository.py`（entity 五函式；`reset_folders_and_photos` 擴充）
- 建：`tests/integration/test_entity_repository.py`

## 資料表（寫進 schema.sql 與 migrate_design3.sql 的定稿）

```sql
CREATE TABLE entity (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,   -- 實體名稱（如「我的 MacBook」）；重名檢查大小寫不敏感在程式層
  description text        NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE photo_entity (               -- 別針：一張照片可釘多個實體（design3 §5 AND）
  photo_id  integer NOT NULL REFERENCES photo (id) ON DELETE CASCADE,  -- 上傳失敗清理 delete_photo 連動
  entity_id integer NOT NULL REFERENCES entity (id),
  pinned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (photo_id, entity_id)       -- 同一張重複釘同一個實體＝撞主鍵（程式層先擋 409）
);

CREATE TABLE task (                       -- 待辦：人按「建立」才寫入（design3 D13）
  id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  photo_id   integer NOT NULL UNIQUE REFERENCES photo (id) ON DELETE CASCADE,  -- UNIQUE＝每張照片至多 1 筆（§7 MVP）
  title      text    NOT NULL,
  due_date   date,                        -- 到期日，可空
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE folder_correction (          -- P35 抽屜糾錯 few-shot 的素材；本 phase 只建表
  id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  suggested  text    NOT NULL,            -- VLM 當時建議的資料夾名稱
  chosen     text    NOT NULL,            -- 使用者實際選的資料夾名稱
  photo_text text    NOT NULL,            -- 那張照片的文字描述（few-shot 例子的題幹）
  created_at timestamptz NOT NULL DEFAULT now()
);
```

- schema.sql DROP 順序改為：photo_entity → task → photo → entity → folder_correction → folder（被指的表後砍）。
- migrate_design3.sql 全部用 `CREATE TABLE IF NOT EXISTS`（可重跑），檔頭註記用途與日期。

## 步驟（先紅再綠）

### 步驟 1：表與安全網

- schema.sql 加四表 → `psql -d PersonalDocAI_test -f db/schema.sql` 重建測試庫。
- `reset_folders_and_photos()` 的 TRUNCATE 改為
  `TRUNCATE photo, folder, entity, folder_correction RESTART IDENTITY CASCADE;`
  （CASCADE 只會連到「指著被清表」的 photo_entity／task；entity 與 folder_correction 沒被 photo 指著，必須自己列進去）。
- 跑全量 `pytest -q` 確認既有 152 顆不掉（安全網相容性檢查）。

### 步驟 2：先紅——`tests/integration/test_entity_repository.py`

1. `test_list_entities_初始為空`：`list_entities()` → `[]`。
2. `test_create_entity_後list拿得到`：`create_entity("我的 MacBook", "2021 M1 Pro")` → 回 dict 含 id/name/description；list 長度 1、名稱原文。
3. `test_find_entity_by_name_大小寫不敏感`：建 "MacBook" 後 `find_entity_by_name("  macbook ")` 命中同一筆；查無回 None。
4. `test_pin與list_photo_entities`：插一張照片（沿用既有 insert_photo 測試手法）→ `pin_entity(photo_id, entity_id)` → `list_photo_entities(photo_id)` 回該實體（含 id/name/description）；未釘的照片回 `[]`。
5. `test_is_pinned`：釘過 True、沒釘 False。
6. `test_同一照片可釘多個實體`：兩個實體都釘 → list 長度 2（依 pinned_at 排序，先釘的在前）。

### 步驟 3：綠——repository 五函式（全部依既有函式的寫法與註解風格）

```python
def list_entities() -> list[dict]         # SELECT id,name,description ORDER BY id
def find_entity_by_name(name) -> dict|None  # WHERE lower(name)=lower(trim(%s))（鏡射 find_folder_by_name）
def create_entity(name, description) -> dict  # INSERT ... RETURNING（不自檢重名，409 屬 P30 router）
def pin_entity(photo_id, entity_id) -> None   # INSERT INTO photo_entity
def is_pinned(photo_id, entity_id) -> bool
def list_photo_entities(photo_id) -> list[dict]  # JOIN entity ORDER BY pinned_at
```

### 步驟 4：正式庫遷移

```bash
pg_dump PersonalDocAI > ~/PersonalDocAI-backup-增量三前.sql   # 先備份
psql -d PersonalDocAI -f db/migrate_design3.sql               # 遷移
psql -d PersonalDocAI -f db/migrate_design3.sql               # 再跑一次證明可重跑
psql -d PersonalDocAI -c "\dt"                                # 六張表都在
```

## 驗收清單

- [x] 新測試先紅再綠（9 顆 RED→GREEN）；全量全綠 163→**172**、零 Ollama 同顆數（controller 複驗）
- [x] `reset_tables` 每測清空四張新表（TRUNCATE 明列 entity／folder_correction；CASCADE 帶到 photo_entity／task）；絕不動正式庫的 assert 仍在
- [x] 正式庫六張表、既有 20 張照片／10 資料夾原封不動、遷移腳本重跑無錯（2026-08-21 controller 親自執行；備份 `~/PersonalDocAI-backup-增量三前.sql`）
- [x] 對外行為零改變：端點數仍 9、上傳回應形狀不變
