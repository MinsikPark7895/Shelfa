import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { publicFetch } from '../api'
import '../styles/Register.css'

function Register() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [name, setName] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showPasswordConfirm, setShowPasswordConfirm] = useState(false)
  const navigate = useNavigate()

  const emailTouched = email.length > 0
  const isEmailValid = /^[a-zA-Z0-9]+@[a-zA-Z0-9]+\.[a-zA-Z0-9]+$/.test(email)

  const passwordTouched = password.length > 0
  const passwordConfirmTouched = passwordConfirm.length > 0

  const validatePassword = (pw: string) => ({
    hasUpperLower: /(?=.*[a-z])(?=.*[A-Z])/.test(pw),
    hasNumber: /[0-9]/.test(pw),
    hasSpecial: /[!@#$%^&*(),.?":{}|<>]/.test(pw),
    hasLength: pw.length >= 8 && pw.length <= 20,
  })

  const validation = validatePassword(password)
  const isPasswordValid = Object.values(validation).every(Boolean)
  const isPasswordMatch = password === passwordConfirm

  const handleRegister = async () => {
    if (!email || !password || !passwordConfirm || !name) {
      alert('모든 항목을 입력해주세요.')
      return
    }

    if (!isEmailValid) {
      alert('올바른 이메일 형식이 아닙니다.')
      return
    }

    if (!isPasswordValid) {
      alert('비밀번호 형식을 확인해주세요.')
      return
    }

    if (!isPasswordMatch) {
      alert('비밀번호가 일치하지 않습니다. 다시 확인해주세요.')
      return
    }

    try {
      const res = await publicFetch('/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password }),
      })

      if (res.ok) {
        navigate('/register/complete')
      } else {
        const err = await res.json().catch(() => ({}))
        const detail = Array.isArray(err?.detail)
          ? err.detail.map((d: { msg: string }) => {
            const msg = d.msg.replace('Value error, ', '')
            if (msg.includes('email')) return '올바른 이메일 형식이 아닙니다.'
            return msg
          }).join('\n')
          : err?.detail || '회원가입에 실패했습니다.'
        alert(detail)
      }
    } catch {
      alert('서버 연결에 실패했습니다.')
    }
  }

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
      </div>

      <div className="register-content">
        <div className="register-card">
          <h1 className="register-title">회원정보 입력</h1>
          <p className="register-desc">회원님의 정보를 입력해주세요.</p>

          <div className="form-group">
            <label className="form-label">이메일</label>
            <div className="input-wrapper">
              <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
              </svg>
              <input
                type="email"
                placeholder="이메일을 입력하세요"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            {emailTouched && !isEmailValid && (
              <p className="password-hint-item">✕ 올바른 이메일 형식이 아닙니다</p>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">비밀번호</label>
            <div className="input-wrapper">
              <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <input
                type={showPassword ? 'text' : 'password'}
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button className="pw-toggle-btn" type="button" onClick={() => setShowPassword(prev => !prev)}>
                {showPassword ? (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
            {passwordTouched && !isPasswordValid && (
              <div className="password-hint-list">
                {!validation.hasUpperLower && <p className="password-hint-item">✕ 영문 대/소문자를 포함해야 합니다</p>}
                {!validation.hasNumber && <p className="password-hint-item">✕ 숫자를 포함해야 합니다</p>}
                {!validation.hasSpecial && <p className="password-hint-item">✕ 특수문자를 포함해야 합니다</p>}
                {!validation.hasLength && <p className="password-hint-item">✕ 8~20자로 입력해야 합니다</p>}
                <p className="password-hint-guide">비밀번호는 8~20자 영문, 숫자, 특수문자를 조합하여 입력하세요</p>
              </div>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">비밀번호 확인</label>
            <div className="input-wrapper">
              <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <input
                type={showPasswordConfirm ? 'text' : 'password'}
                placeholder="비밀번호를 다시 입력하세요"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
              />
              <button className="pw-toggle-btn" type="button" onClick={() => setShowPasswordConfirm(prev => !prev)}>
                {showPasswordConfirm ? (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
            {passwordConfirmTouched && !isPasswordMatch && (
              <p className="password-hint-item">✕ 비밀번호가 일치하지 않습니다</p>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">사용자 이름</label>
            <div className="input-wrapper">
              <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 3l4 4-10 10H7v-4L17 3z" />
              </svg>
              <input
                type="text"
                placeholder="이름을 입력하세요"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
          </div>

          <button className="primary-btn register-btn" onClick={handleRegister}>회원가입</button>
        </div>
      </div>
    </div>
  )
}

export default Register
