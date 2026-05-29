import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Login.css'

function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()

  const handleLogin = async () => {
    if (!username || !password) {
      alert('아이디와 비밀번호를 입력해주세요.')
      return
    }

    try {
      const res = await fetch(`http://localhost:3001/users?username=${username}`)
      const users = await res.json()

      if (users.length === 0) {
        alert('존재하지 않는 아이디입니다.')
        return
      }

      const user = users[0]
      if (user.password !== password) {
        alert('비밀번호가 틀렸습니다.')
        return
      }

      localStorage.setItem('user', JSON.stringify(user))
      navigate('/home')
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

      <div className="login-content">
        <p className="welcome-text">
          디지털 도서관 서비스를<br />
          이용하시려면 로그인 해주세요.
        </p>

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
              onKeyDown={(e) => { if (e.key === 'Enter') handleLogin() }}
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
              onKeyDown={(e) => { if (e.key === 'Enter') handleLogin() }}
            />
          </div>
        </div>

        <div className="options-row">
          <label className="checkbox-wrapper">
            <input type="checkbox" />
            <span className="checkbox-label">아이디 저장</span>
          </label>
        </div>

        <button className="primary-btn" onClick={handleLogin}>로그인</button>

        <div className="divider"></div>

        <div className="sub-links">
          <a onClick={() => navigate('/register')}>회원가입</a>
          <div className="sep"></div>
          <a onClick={() => navigate('/findid')}>아이디 찾기</a>
          <div className="sep"></div>
          <a onClick={() => navigate('/resetpassword')}>비밀번호 재설정</a>
        </div>

        <div className="social-section">
          <p className="social-label">간편 로그인</p>
          <div className="social-buttons">
            <button className="social-btn kakao" onClick={() => alert('간편 로그인 기능은 향후 개발 예정입니다.')}>
              <svg viewBox="0 0 24 24" fill="#3C1E1E"><path d="M12 3C6.48 3 2 6.58 2 10.94c0 2.8 1.87 5.27 4.68 6.67-.15.56-.96 3.6-.99 3.83 0 0-.02.17.09.24.11.06.24.01.24.01.32-.04 3.7-2.44 4.28-2.85.55.08 1.11.12 1.7.12 5.52 0 10-3.58 10-7.97C22 6.58 17.52 3 12 3z" /></svg>
            </button>
            <button className="social-btn naver" onClick={() => alert('간편 로그인 기능은 향후 개발 예정입니다.')}>
              <svg viewBox="0 0 24 24" fill="white"><path d="M14.4 12.82L9.26 5.4H5.4v13.2h4.2V11.18L14.74 18.6H18.6V5.4h-4.2v7.42z" /></svg>
            </button>
            <button className="social-btn google" onClick={() => alert('간편 로그인 기능은 향후 개발 예정입니다.')}>
              <svg viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" /><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" /><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" /><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" /></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Login
