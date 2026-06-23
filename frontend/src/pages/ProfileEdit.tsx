import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'
import '../styles/ProfileEdit.css'

function ProfileEdit() {
  const navigate = useNavigate()
  const user = (() => { try { return JSON.parse(localStorage.getItem('user') || '{}') } catch { return {} } })()

  // 비밀번호 변경 폼 토글
  const [showPwForm, setShowPwForm] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [showNewConfirm, setShowNewConfirm] = useState(false)

  const newPwTouched = newPassword.length > 0
  const newPwConfirmTouched = newPasswordConfirm.length > 0

  const validatePassword = (pw: string) => ({
    hasUpperLower: /(?=.*[a-z])(?=.*[A-Z])/.test(pw),
    hasNumber: /[0-9]/.test(pw),
    hasSpecial: /[!@#$%^&*(),.?":{}|<>]/.test(pw),
    hasLength: pw.length >= 8 && pw.length <= 20,
  })

  const validation = validatePassword(newPassword)
  const isNewPwValid = Object.values(validation).every(Boolean)
  const isNewPwMatch = newPassword === newPasswordConfirm

  const handleChangePassword = async () => {
    if (!currentPassword || !newPassword || !newPasswordConfirm) {
      alert('모든 항목을 입력해주세요.')
      return
    }
    if (!isNewPwValid) {
      alert('새 비밀번호 형식을 확인해주세요.')
      return
    }
    if (!isNewPwMatch) {
      alert('새 비밀번호가 일치하지 않습니다.')
      return
    }
    try {
      const res = await apiFetch('/users/me/password', {
        method: 'PUT',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      if (res.ok) {
        alert('비밀번호가 변경되었습니다. 다시 로그인해주세요.')
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
        navigate('/login')
      } else {
        const err = await res.json().catch(() => ({}))
        alert(err?.detail || '비밀번호 변경에 실패했습니다.')
      }
    } catch {
      alert('서버 연결에 실패했습니다.')
    }
  }

  const handleWithdraw = async () => {
    if (!confirm('정말 탈퇴하시겠습니까?\n대출 중인 도서가 있으면 탈퇴할 수 없습니다.')) return
    try {
      const res = await apiFetch('/users/me', { method: 'DELETE' })
      if (res.ok) {
        alert('회원 탈퇴가 완료되었습니다.')
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
        navigate('/login')
      } else {
        const err = await res.json().catch(() => ({}))
        alert(err?.detail || '회원 탈퇴에 실패했습니다.')
      }
    } catch {
      alert('서버 연결에 실패했습니다.')
    }
  }

  const EyeIcon = ({ open }: { open: boolean }) => open ? (
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
  )

  return (
    <div className="page-container">
      <div className="top-nav">
        <button className="pe-back-btn" onClick={() => navigate('/mypage')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <span className="logo-text">계정 설정</span>
      </div>

      <div className="pe-content">
        {/* 내 프로필 섹션 */}
        <div className="pe-section">
          <div className="pe-section-header">내 프로필</div>
          <div className="pe-list">
            <div className="pe-list-item">
              <div className="pe-item-left">
                <svg className="pe-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
                </svg>
                <span className="pe-item-label">{user.name || '-'}</span>
              </div>
            </div>
            <div className="pe-list-item">
              <div className="pe-item-left">
                <svg className="pe-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" />
                </svg>
                <span className="pe-item-label">{user.email || '-'}</span>
              </div>
            </div>
            <div className="pe-list-item" onClick={handleWithdraw}>
              <div className="pe-item-left">
                <svg className="pe-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
                </svg>
                <span className="pe-item-label">회원탈퇴</span>
              </div>
              <span className="pe-item-action withdraw">탈퇴하기</span>
            </div>
          </div>
        </div>

        {/* 보안 설정 섹션 */}
        <div className="pe-section">
          <div className="pe-section-header">보안설정</div>
          <div className="pe-list">
            <div className="pe-list-item" onClick={() => setShowPwForm(!showPwForm)}>
              <div className="pe-item-left">
                <svg className="pe-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
                <span className="pe-item-label">비밀번호</span>
              </div>
              <span className="pe-item-action">수정</span>
            </div>

            {showPwForm && (
              <div className="pe-pw-form">
                <div className="form-group">
                  <label className="form-label">현재 비밀번호</label>
                  <div className="input-wrapper">
                    <input type={showCurrent ? 'text' : 'password'} placeholder="현재 비밀번호" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
                    <button className="pw-toggle-btn" type="button" onClick={() => setShowCurrent(p => !p)}><EyeIcon open={showCurrent} /></button>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">새 비밀번호</label>
                  <div className="input-wrapper">
                    <input type={showNew ? 'text' : 'password'} placeholder="새 비밀번호" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                    <button className="pw-toggle-btn" type="button" onClick={() => setShowNew(p => !p)}><EyeIcon open={showNew} /></button>
                  </div>
                  {newPwTouched && !isNewPwValid && (
                    <div className="password-hint-list">
                      {!validation.hasUpperLower && <p className="password-hint-item">✕ 영문 대/소문자를 포함해야 합니다</p>}
                      {!validation.hasNumber && <p className="password-hint-item">✕ 숫자를 포함해야 합니다</p>}
                      {!validation.hasSpecial && <p className="password-hint-item">✕ 특수문자를 포함해야 합니다</p>}
                      {!validation.hasLength && <p className="password-hint-item">✕ 8~20자로 입력해야 합니다</p>}
                    </div>
                  )}
                </div>
                <div className="form-group">
                  <label className="form-label">새 비밀번호 확인</label>
                  <div className="input-wrapper">
                    <input type={showNewConfirm ? 'text' : 'password'} placeholder="새 비밀번호 확인" value={newPasswordConfirm} onChange={(e) => setNewPasswordConfirm(e.target.value)} />
                    <button className="pw-toggle-btn" type="button" onClick={() => setShowNewConfirm(p => !p)}><EyeIcon open={showNewConfirm} /></button>
                  </div>
                  {newPwConfirmTouched && !isNewPwMatch && (
                    <p className="password-hint-item">✕ 새 비밀번호가 일치하지 않습니다</p>
                  )}
                </div>
                <button className="primary-btn pe-pw-btn" onClick={handleChangePassword}>비밀번호 변경</button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ProfileEdit
