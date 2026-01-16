# Contributing Guide / 기여 가이드

[English](#english) | [한국어](#한국어)

---

## 한국어

Upbit 모의 투자 대회 시스템에 기여해 주셔서 감사합니다!

### 기여 방법

1. **Fork**: 이 저장소를 Fork 합니다.
2. **Branch**: 새 기능이나 버그 수정을 위한 브랜치를 생성합니다.
   ```bash
   git checkout -b feature/your-feature-name
   # 또는
   git checkout -b fix/your-bug-fix
   ```
3. **Commit**: 변경사항을 커밋합니다.
   ```bash
   git commit -m "feat: 새로운 기능 추가"
   ```
4. **Push**: 브랜치를 푸시합니다.
   ```bash
   git push origin feature/your-feature-name
   ```
5. **Pull Request**: GitHub에서 Pull Request를 생성합니다.

### 커밋 메시지 규칙

커밋 메시지는 다음 형식을 따릅니다:

- `feat:` 새로운 기능
- `fix:` 버그 수정
- `docs:` 문서 변경
- `style:` 코드 포맷팅 (기능 변경 없음)
- `refactor:` 코드 리팩토링
- `test:` 테스트 추가/수정
- `chore:` 기타 변경사항

### 코드 스타일

- Python: PEP 8 스타일 가이드를 따릅니다.
- JavaScript: 기존 코드 스타일을 유지합니다.
- 한글 주석을 사용해도 됩니다.

### 개발 환경 설정

```bash
# 저장소 클론
git clone https://github.com/your-username/upbit-coin-contest.git
cd upbit-coin-contest

# 가상 환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일 편집

# 개발 서버 실행
python api.py
```

### Pull Request 가이드라인

- PR 제목은 변경사항을 명확히 설명해야 합니다.
- 관련 이슈가 있다면 연결해 주세요 (`Fixes #123`).
- 새로운 기능에는 테스트를 추가해 주세요.
- 기존 테스트가 모두 통과하는지 확인해 주세요.

### 문의

질문이 있으시면 Issue를 생성해 주세요.

---

## English

Thank you for your interest in contributing to the Upbit Mock Trading Contest!

### How to Contribute

1. **Fork**: Fork this repository.
2. **Branch**: Create a branch for your feature or bug fix.
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```
3. **Commit**: Commit your changes.
   ```bash
   git commit -m "feat: add new feature"
   ```
4. **Push**: Push your branch.
   ```bash
   git push origin feature/your-feature-name
   ```
5. **Pull Request**: Create a Pull Request on GitHub.

### Commit Message Convention

Follow this format for commit messages:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code formatting (no functional changes)
- `refactor:` Code refactoring
- `test:` Adding/modifying tests
- `chore:` Other changes

### Code Style

- Python: Follow PEP 8 style guide.
- JavaScript: Maintain existing code style.
- Korean comments are acceptable.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/your-username/upbit-coin-contest.git
cd upbit-coin-contest

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env file

# Run development server
python api.py
```

### Pull Request Guidelines

- PR title should clearly describe the changes.
- Link related issues if any (`Fixes #123`).
- Add tests for new features.
- Ensure all existing tests pass.

### Questions

If you have questions, please create an Issue.
