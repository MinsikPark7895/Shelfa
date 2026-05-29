import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Register.css'

function Register() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const navigate = useNavigate()

  const handleRegister = async () => {
    if (!username || !password || !name) {
      alert('모든 항목을 입력해주세요.')
      return
    }

    try {
      const res = await fetch('/api/v1/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, username, password })
      })
      const data = await res.json()

      if (res.ok) {
        alert('회원가입이 완료되었습니다.')
        navigate('/')
      } else {
        alert(data.detail || '회원가입에 실패했습니다.')
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
            <label className="form-label">아이디</label>
            <div className="input-wrapper">
              <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
              </svg>
              <input
                type="text"
                placeholder="아이디를 입력하세요"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">비밀번호</label>
            <div className="input-wrapper">
              <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <input
                type="password"
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div className="input-hint">
              <span className="check">✓</span>영문 대/소문자 <span className="check">✓</span>숫자 <span className="check">✓</span>특수문자 <span className="check">✓</span>8-20자
            </div>
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