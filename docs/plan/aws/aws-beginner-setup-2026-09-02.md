# AWS 新手開戶與 CLI 設定

> 查證日期：2026-09-02  
> 目標：完成 AWS Free plan 開戶、安全設定、費用警報，以及讓這台 Mac 可以安全使用 AWS CLI。  
> 今天**不建立 S3、SQS、EC2 或其他雲端資源**。

---

## 0. 先準備

- 一個可收信的 email
- 手機
- 信用卡或簽帳卡
- Mac 上已安裝 Homebrew

AWS 註冊會要求付款方式。官方說卡片驗證可能暫時出現 **USD $1**，驗證後退回；銀行可能需要約 **3–5 天**顯示退款。

---

## 1. 建立 AWS Free plan 帳號

1. 打開：<https://aws.amazon.com/free/>
2. 點 **Create a free account**。
3. 按畫面完成：
   - Email
   - AWS account name
   - 聯絡資料
   - 手機驗證
   - 信用卡／簽帳卡驗證
4. Account type 若只是學習，選 **Personal**。
5. 方案選 **Free plan**。
6. Support plan 選免費的 **Basic Support**。

### Free plan 你只要記住

- 新客戶一開始有 **USD $100 credits**。
- 完成指定 Explore AWS 活動，最多可再拿 **USD $100 credits**。
- Free plan 最長 **6 個月**，或 credits 用完時提前結束。
- Free plan 不會向你收一般 AWS 使用費，除非你升級到 Paid plan 或啟用 paid-only 功能。
- **不要加入 AWS Organizations，也不要設定 Control Tower。**

官方：<https://aws.amazon.com/free/>

---

## 2. 立刻幫 root 帳號開 MFA

`root user` 就是你註冊 AWS 時建立的最高權限帳號。

登入 AWS Console 後：

1. 右上角帳號名稱 → **Security credentials**
2. 找到 **Multi-factor authentication (MFA)**
3. 點 **Assign MFA device**
4. 選 **Authenticator app**
5. 用 Google Authenticator、Microsoft Authenticator、1Password 等掃 QR code
6. 依畫面輸入驗證碼完成設定

### 重要

- **不要替 root 建 Access Key**
- 之後不要用 root 做日常 AWS 操作

官方：<https://docs.aws.amazon.com/IAM/latest/UserGuide/root-user-best-practices.html>

---

## 3. 建立 $5/月 Budget 警報

這一步是為了讓異常使用量提早寄信提醒你。

AWS Console 搜尋：

**Billing and Cost Management → Budgets → Create budget**

設定：

- Budget type：**Cost budget**
- Period：**Monthly**
- Budget amount：**USD $5**
- Budget name：`personaldocai-budget`

建立兩個 email alerts：

| Alert | Threshold |
|---|---:|
| Actual cost | 80% |
| Forecasted cost | 80% |

也就是花到／預測會花到 **$4** 時寄信。

只使用 Budget monitoring + email notification 是免費的。

官方：<https://docs.aws.amazon.com/cost-management/latest/userguide/create-cost-budget.html>

---

## 4. 允許管理員之後查看 Billing

這個開關只能由 root 開。

使用 root：

**Account → IAM user and role access to Billing information → Edit → Activate IAM Access → Update**

完成後才繼續下一步。

官方：<https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-getting-started.html>

---

## 5. 建立日常管理員

AWS Console 搜尋：

**IAM → Users → Create user**

建立：

```text
personaldocai-admin
```

給它 Console access，並加入這兩個 AWS managed policies：

```text
AdministratorAccess
SignInLocalDevelopmentAccess
```

完成後：

1. 幫 `personaldocai-admin` 設 MFA
2. 登出 root
3. 之後日常使用 `personaldocai-admin`

### 不要做

**不要建立 Access Key。**

我們會使用 AWS 現在推薦的 `aws login` 暫時憑證。

官方：  
<https://docs.aws.amazon.com/signin/latest/userguide/command-line-sign-in.html>

---

## 6. 在 Mac 安裝 AWS CLI v2

Terminal：

```bash
brew install awscli
```

確認版本：

```bash
aws --version
```

你需要看到：

```text
aws-cli/2.x.x
```

而且 `aws login` 需要 AWS CLI **2.32.0 以上**。

如果版本低於 2.32：

```bash
brew update
brew upgrade awscli
```

官方 AWS CLI 安裝文件：  
<https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>

---

## 7. 用管理員登入 AWS CLI

在 Terminal：

```bash
aws login --profile personaldocai-admin
```

瀏覽器會開啟 AWS 登入頁。

使用：

```text
personaldocai-admin
```

登入並完成 MFA。

如果 CLI 問 Default Region，而此專案使用東京：

```text
ap-northeast-1
```

接著設定輸出格式：

```bash
aws configure set output json --profile personaldocai-admin
```

---

## 8. 確認 CLI 成功連上 AWS

執行：

```bash
aws sts get-caller-identity --profile personaldocai-admin
```

成功會看到類似：

```json
{
  "UserId": "...",
  "Account": "123456789012",
  "Arn": "..."
}
```

看到 `Account`、`UserId`、`Arn` 就代表 Mac 已成功登入 AWS。

**不要把 Account ID、密碼、Access Key 或任何 credential 貼到 GitHub。**

---

# 到這裡停止

今天完成後，你應該只有：

- [ ] AWS Free plan 帳號
- [ ] root MFA
- [ ] $5/月 Budget alerts
- [ ] IAM Billing access 已開
- [ ] `personaldocai-admin`
- [ ] admin MFA
- [ ] AWS CLI v2
- [ ] `aws login` 成功
- [ ] `aws sts get-caller-identity` 成功

今天**不要建立任何 AWS resource**。

---

## 今天不要做

- 不要 Upgrade to Paid
- 不要加入 AWS Organizations
- 不要開 AWS Control Tower
- 不要建立 EC2
- 不要建立 S3
- 不要建立 SQS
- 不要建立 RDS
- 不要建立長期 Access Key
- 不要把 AWS credential 放進 `.env` 或 Git

---

## 官方來源

1. AWS Free Tier  
   <https://aws.amazon.com/free/>

2. AWS Free Tier / account registration FAQ  
   <https://aws.amazon.com/free/registration-faqs/>

3. AWS root user security best practices  
   <https://docs.aws.amazon.com/IAM/latest/UserGuide/root-user-best-practices.html>

4. AWS Budgets  
   <https://docs.aws.amazon.com/cost-management/latest/userguide/create-cost-budget.html>

5. Billing IAM access  
   <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-getting-started.html>

6. AWS CLI `aws login`  
   <https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html>

7. AWS CLI authentication recommendations  
   <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-quickstart.html>
