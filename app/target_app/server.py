"""
Apex CoreBank Console v4.2 - Legacy Banking Back-Office System.
Simulates realistic legacy banking UI: nested tables, iframe dialogs,
non-semantic markup, business error states, transient maintenance modals,
and irreversible high-risk account operations.
"""
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import uvicorn

app = FastAPI(title="Apex CoreBank Console v4.2", description="Legacy Back-Office Banking Simulation")

# In-memory mock bank database
MEMBERS_DB: Dict[str, Dict[str, Any]] = {
    "10042": {
        "id": "10042",
        "name": "Jane Doe",
        "ssn_masked": "***-**-6789",
        "status": "ACTIVE",
        "branch": "Main St Branch #104",
        "joined_date": "2018-04-12",
        "accounts": {
            "savings": {"account_number": "00910042-01", "balance": 12450.75, "type": "Regular Savings"},
            "checking": {"account_number": "00910042-02", "balance": 3210.50, "type": "Premier Checking"},
        },
        "sub_accounts": [],
    },
    "20088": {
        "id": "20088",
        "name": "Robert Martinez",
        "ssn_masked": "***-**-4321",
        "status": "ACTIVE",
        "branch": "Metro Plaza #002",
        "joined_date": "2020-09-18",
        "accounts": {
            "savings": {"account_number": "00920088-01", "balance": 54800.00, "type": "Regular Savings"},
            "checking": {"account_number": "00920088-02", "balance": 8120.00, "type": "Premier Checking"},
        },
        "sub_accounts": [],
    },
    "30199": {
        "id": "30199",
        "name": "Sarah Jenkins",
        "ssn_masked": "***-**-9912",
        "status": "FROZEN",
        "branch": "Westside Hub #018",
        "joined_date": "2015-11-03",
        "accounts": {
            "savings": {"account_number": "00930199-01", "balance": 450.20, "type": "Regular Savings"},
            "checking": {"account_number": "00930199-02", "balance": 12.00, "type": "Standard Checking"},
        },
        "sub_accounts": [],
    },
}

BASE_CSS = """
<style>
  body { font-family: Tahoma, 'MS Sans Serif', Arial, sans-serif; background-color: #f0f0f4; margin: 0; padding: 0; font-size: 12px; color: #222; }
  .header-bar { background: linear-gradient(to bottom, #1e4b88, #112d56); color: #fff; padding: 8px 16px; border-bottom: 2px solid #0a1c38; }
  .header-bar h1 { margin: 0; font-size: 16px; font-weight: bold; }
  .nav-tabs { background: #dcdfe6; border-bottom: 1px solid #999; padding: 4px 16px 0 16px; }
  .nav-tabs a { display: inline-block; padding: 6px 14px; background: #c0c4cc; color: #222; text-decoration: none; border: 1px solid #999; border-bottom: none; border-radius: 4px 4px 0 0; margin-right: 4px; font-weight: bold; }
  .nav-tabs a.active { background: #f0f0f4; color: #112d56; border-bottom: 1px solid #f0f0f4; margin-bottom: -1px; }
  .content-area { padding: 16px; }
  .legacy-fieldset { border: 1px solid #999; padding: 12px; background: #fff; margin-bottom: 16px; border-radius: 2px; }
  .legacy-fieldset legend { font-weight: bold; color: #112d56; padding: 0 6px; }
  .legacy-table { width: 100%; border-collapse: collapse; margin-top: 8px; background: #fff; }
  .legacy-table th { background: #e2e6ef; border: 1px solid #b0b8c8; padding: 6px 8px; text-align: left; font-size: 11px; color: #333; }
  .legacy-table td { border: 1px solid #d0d5df; padding: 6px 8px; font-size: 11px; }
  .legacy-table tr:nth-child(even) { background-color: #f9fafc; }
  .btn-legacy { background: linear-gradient(to bottom, #f5f5f5, #dcdcdc); border: 1px solid #777; padding: 4px 12px; font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 2px; }
  .btn-legacy:hover { background: #e0e0e0; }
  .btn-danger { background: linear-gradient(to bottom, #d9534f, #c9302c); color: #fff; border: 1px solid #ac2925; padding: 5px 14px; font-weight: bold; cursor: pointer; border-radius: 2px; }
  .btn-danger:hover { background: #c9302c; }
  .alert-box { padding: 10px 14px; border-radius: 2px; margin-bottom: 12px; font-weight: bold; }
  .alert-danger { background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
  .alert-warning { background-color: #fff3cd; border: 1px solid #ffeeba; color: #856404; }
  .alert-success { background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
  .badge-active { background: #28a745; color: #fff; padding: 2px 6px; border-radius: 2px; font-size: 10px; font-weight: bold; }
  .badge-frozen { background: #dc3545; color: #fff; padding: 2px 6px; border-radius: 2px; font-size: 10px; font-weight: bold; }
  .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
  .modal-content { background: #fff; border: 2px solid #112d56; padding: 16px; border-radius: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); max-width: 450px; width: 100%; }
</style>
"""


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "Apex CoreBank Console", "version": "4.2.0"}


@app.get("/", response_class=HTMLResponse)
@app.get("/console", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/console/members")


@app.get("/console/members", response_class=HTMLResponse)
async def members_page(interstitial: Optional[str] = None):
    interstitial_html = ""
    if interstitial == "true":
        interstitial_html = """
        <div id="maintenance_notice_modal" class="modal-overlay">
          <div class="modal-content">
            <h3 style="margin-top:0; color:#856404;">⚠️ System Maintenance Notice</h3>
            <p>Apex CoreBank nightly batch processing is scheduled for 02:00 UTC. System operations may experience minor delays.</p>
            <div style="text-align: right; margin-top: 14px;">
              <button id="btn_dismiss_notice" class="btn-legacy" onclick="document.getElementById('maintenance_notice_modal').style.display='none'">Dismiss Notice</button>
            </div>
          </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Apex CoreBank Console - Member Services</title>
  {BASE_CSS}
</head>
<body>
  {interstitial_html}
  <div class="header-bar">
    <h1>Apex CoreBank OS v4.2 [Production - Node #04]</h1>
  </div>
  <div class="nav-tabs">
    <a href="/console/members" class="active">Member Inquiry</a>
    <a href="/console/accounts/open">Open Sub-Account</a>
  </div>
  <div class="content-area">
    <h2 aria-label="Member Services Console" style="color: #112d56; margin-top: 0;">Member Services Console</h2>
    <fieldset class="legacy-fieldset">
      <legend>Search Member Records</legend>
      <form name="searchForm" action="/console/members/search" method="GET">
        <table border="0" cellpadding="4" cellspacing="2">
          <tr>
            <td><strong>Member ID / Account #:</strong></td>
            <td>
              <input type="text" name="memberId" class="legacy-input" aria-label="Member ID / Account #" placeholder="e.g. 10042" style="width: 180px; padding: 3px;" required />
            </td>
            <td>
              <button type="submit" name="btnSearch" class="btn-legacy" aria-label="Search Records">Search</button>
            </td>
          </tr>
        </table>
      </form>
    </fieldset>

    <div style="margin-top: 16px; color: #666; font-size: 11px;">
      <p>💡 Tip: Enter <strong>10042</strong> or <strong>20088</strong> for active members, <strong>30199</strong> for frozen accounts, or <strong>99999</strong> to simulate record-not-found.</p>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/console/members/search", response_class=HTMLResponse)
async def member_search(memberId: str):
    member_id = memberId.strip()
    if member_id not in MEMBERS_DB:
        # Expected Business Outcome: Record Not Found
        html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Apex CoreBank Console - Search Result</title>
  {BASE_CSS}
</head>
<body>
  <div class="header-bar">
    <h1>Apex CoreBank OS v4.2 [Production - Node #04]</h1>
  </div>
  <div class="nav-tabs">
    <a href="/console/members" class="active">Member Inquiry</a>
    <a href="/console/accounts/open">Open Sub-Account</a>
  </div>
  <div class="content-area">
    <div class="alert-box alert-danger" id="error_container">
      <span id="lbl_errorMessage">Error: Member ID not found in core database (ID: {member_id})</span>
    </div>
    <p>Please verify the account identifier and query again.</p>
    <a href="/console/members" class="btn-legacy" style="text-decoration:none; display:inline-block;">&laquo; Back to Member Search</a>
  </div>
</body>
</html>"""
        return HTMLResponse(content=html)

    member = MEMBERS_DB[member_id]
    status_badge = f'<span id="badge_status" class="badge-active">{member["status"]}</span>' if member["status"] == "ACTIVE" else f'<span id="badge_status" class="badge-frozen">{member["status"]}</span>'
    
    sub_accounts_rows = ""
    for sub in member["sub_accounts"]:
        sub_accounts_rows += f"""
        <tr>
          <td>{sub['account_number']}</td>
          <td>{sub['type']}</td>
          <td class="bal-val" style="text-align: right; font-weight: bold;">${sub['balance']:,.2f}</td>
          <td><span class="badge-active">ACTIVE</span></td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Apex CoreBank Console - Member #{member['id']}</title>
  {BASE_CSS}
</head>
<body>
  <div class="header-bar">
    <h1>Apex CoreBank OS v4.2 [Production - Node #04]</h1>
  </div>
  <div class="nav-tabs">
    <a href="/console/members" class="active">Member Inquiry</a>
    <a href="/console/accounts/open">Open Sub-Account</a>
  </div>
  <div class="content-area">
    <fieldset class="legacy-fieldset">
      <legend>Member Profile Summary</legend>
      <table border="0" cellpadding="4" cellspacing="2" style="width: 100%;">
        <tr>
          <td style="width: 150px; color:#555;"><strong>Member ID:</strong></td>
          <td id="lbl_memberId" style="font-weight:bold;">{member['id']}</td>
          <td style="width: 150px; color:#555;"><strong>SSN (Masked):</strong></td>
          <td id="lbl_memberSsn">{member['ssn_masked']}</td>
        </tr>
        <tr>
          <td style="color:#555;"><strong>Full Legal Name:</strong></td>
          <td id="lbl_memberName" style="font-weight:bold; color:#112d56;">{member['name']}</td>
          <td style="color:#555;"><strong>Account Status:</strong></td>
          <td>{status_badge}</td>
        </tr>
        <tr>
          <td style="color:#555;"><strong>Assigned Branch:</strong></td>
          <td id="lbl_branch">{member['branch']}</td>
          <td style="color:#555;"><strong>Enrolled Date:</strong></td>
          <td>{member['joined_date']}</td>
        </tr>
      </table>
    </fieldset>

    <fieldset class="legacy-fieldset">
      <legend>Active Account Balances</legend>
      <table class="legacy-table account-summary-table" id="tbl_balances">
        <thead>
          <tr>
            <th>Account Number</th>
            <th>Product Description</th>
            <th style="text-align: right;">Current Ledger Balance</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{member['accounts']['savings']['account_number']}</td>
            <td>{member['accounts']['savings']['type']}</td>
            <td class="bal-val" style="text-align: right; font-weight: bold; color: #0b6b28;">
              ${member['accounts']['savings']['balance']:,.2f}
            </td>
            <td><span class="badge-active">OPEN</span></td>
          </tr>
          <tr>
            <td>{member['accounts']['checking']['account_number']}</td>
            <td>{member['accounts']['checking']['type']}</td>
            <td class="bal-val" style="text-align: right; font-weight: bold; color: #0b6b28;">
              ${member['accounts']['checking']['balance']:,.2f}
            </td>
            <td><span class="badge-active">OPEN</span></td>
          </tr>
          {sub_accounts_rows}
        </tbody>
      </table>
    </fieldset>

    <div style="margin-top: 12px;">
      <a href="/console/members" class="btn-legacy" style="text-decoration:none; display:inline-block;">&laquo; New Search</a>
      <a href="/console/accounts/open?memberId={member['id']}" class="btn-legacy" style="text-decoration:none; display:inline-block; margin-left: 8px;">+ Open Sub-Account</a>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/console/accounts/open", response_class=HTMLResponse)
async def open_account_page(memberId: Optional[str] = "10042"):
    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Apex CoreBank Console - Open Sub-Account</title>
  {BASE_CSS}
  <script>
    function showConfirmationIframe() {{
      var modal = document.getElementById('confirmation_modal');
      var iframe = document.getElementById('dialog_frame');
      var memberId = document.getElementById('input_member_id').value;
      var accType = document.getElementById('select_account_type').value;
      var deposit = document.getElementById('input_deposit').value;
      
      iframe.src = '/console/dialogs/confirm-frame?memberId=' + encodeURIComponent(memberId) + '&accType=' + encodeURIComponent(accType) + '&deposit=' + encodeURIComponent(deposit);
      modal.style.display = 'flex';
    }}
  </script>
</head>
<body>
  <div class="header-bar">
    <h1>Apex CoreBank OS v4.2 [Production - Node #04]</h1>
  </div>
  <div class="nav-tabs">
    <a href="/console/members">Member Inquiry</a>
    <a href="/console/accounts/open" class="active">Open Sub-Account</a>
  </div>
  <div class="content-area">
    <h2 aria-label="Open New Deposit Sub-Account" style="color: #112d56; margin-top: 0;">Open New Deposit Sub-Account</h2>
    
    <fieldset class="legacy-fieldset">
      <legend>Account Configuration</legend>
      <form id="openAccountForm" onsubmit="event.preventDefault(); showConfirmationIframe();">
        <table border="0" cellpadding="6" cellspacing="2">
          <tr>
            <td style="width: 160px;"><strong>Member ID:</strong></td>
            <td>
              <input type="text" id="input_member_id" name="memberId" value="{memberId}" aria-label="Target Member ID" class="legacy-input" required />
            </td>
          </tr>
          <tr>
            <td><strong>Product Type:</strong></td>
            <td>
              <select id="select_account_type" name="accountType" aria-label="Sub-Account Product Type" class="legacy-input">
                <option value="Money Market">High-Yield Money Market (3.85% APY)</option>
                <option value="Certificate of Deposit">12-Month Certificate of Deposit (4.50% APY)</option>
                <option value="Holiday Club Savings">Holiday Club Dedicated Savings</option>
              </select>
            </td>
          </tr>
          <tr>
            <td><strong>Opening Deposit ($):</strong></td>
            <td>
              <input type="number" id="input_deposit" name="initialDeposit" value="500.00" step="0.01" min="25.00" aria-label="Opening Deposit Amount" class="legacy-input" required />
            </td>
          </tr>
          <tr>
            <td></td>
            <td style="padding-top: 10px;">
              <button type="submit" id="btn_proceed_confirmation" class="btn-legacy" aria-label="Proceed to Authorization">Proceed to Authorization &raquo;</button>
            </td>
          </tr>
        </table>
      </form>
    </fieldset>

    <!-- IFRAME Confirmation Modal Dialog (Simulates Legacy Iframe Security Gate) -->
    <div id="confirmation_modal" class="modal-overlay" style="display: none;">
      <div class="modal-content" style="max-width: 520px; padding: 4px;">
        <div style="background:#112d56; color:#fff; padding:6px 10px; display:flex; justify-content:space-between; font-weight:bold;">
          <span>High-Risk Transaction Authorization</span>
          <button onclick="document.getElementById('confirmation_modal').style.display='none'" style="background:none; border:none; color:#fff; cursor:pointer; font-weight:bold;">✕</button>
        </div>
        <iframe id="dialog_frame" name="dialog_frame" src="about:blank" style="width: 100%; height: 260px; border: none;"></iframe>
      </div>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/console/dialogs/confirm-frame", response_class=HTMLResponse)
async def confirm_dialog_frame(memberId: str, accType: str, deposit: str):
    html = f"""<!DOCTYPE html>
<html>
<head>
  {BASE_CSS}
</head>
<body style="background: #fff; padding: 12px;">
  <div class="alert-box alert-warning" style="margin-bottom: 8px;">
    ⚠️ <strong>IRREVERSIBLE BANKING ACTION</strong>
  </div>
  <p style="margin: 4px 0 10px 0;">You are about to bind and provision a new deposit instrument in core banking ledger.</p>
  
  <table class="legacy-table" style="margin-bottom: 14px;">
    <tr><td style="width:130px;"><strong>Member ID:</strong></td><td id="lbl_confirm_member">{memberId}</td></tr>
    <tr><td><strong>Instrument:</strong></td><td id="lbl_confirm_type">{accType}</td></tr>
    <tr><td><strong>Opening Deposit:</strong></td><td id="lbl_confirm_deposit">${float(deposit):,.2f}</td></tr>
  </table>

  <form action="/console/accounts/create" method="POST" target="_parent">
    <input type="hidden" name="memberId" value="{memberId}" />
    <input type="hidden" name="accountType" value="{accType}" />
    <input type="hidden" name="initialDeposit" value="{deposit}" />
    <div style="display:flex; justify-content: space-between; align-items: center;">
      <button type="button" class="btn-legacy" onclick="window.parent.document.getElementById('confirmation_modal').style.display='none'">Cancel</button>
      <button type="submit" id="btn_authorize_creation" class="btn-danger" aria-label="Authorize Creation">Authorize Creation</button>
    </div>
  </form>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/console/accounts/create", response_class=HTMLResponse)
async def create_account(memberId: str = Form(...), accountType: str = Form(...), initialDeposit: str = Form(...)):
    member_id = memberId.strip()
    deposit = float(initialDeposit)
    
    if member_id in MEMBERS_DB:
        new_acc_num = f"009{member_id}-0{len(MEMBERS_DB[member_id]['sub_accounts']) + 3}"
        MEMBERS_DB[member_id]["sub_accounts"].append({
            "account_number": new_acc_num,
            "type": accountType,
            "balance": deposit,
        })
    else:
        new_acc_num = f"009{member_id}-99"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Apex CoreBank Console - Creation Confirmed</title>
  {BASE_CSS}
</head>
<body>
  <div class="header-bar">
    <h1>Apex CoreBank OS v4.2 [Production - Node #04]</h1>
  </div>
  <div class="content-area">
    <div class="alert-box alert-success" id="confirmation_success_container">
      <h3>✓ Sub-Account Successfully Created & Provisioned</h3>
      <p>Ledger Account Reference: <strong id="lbl_new_account_number">{new_acc_num}</strong></p>
      <p>Initial Balance: <strong id="lbl_confirmed_deposit">${deposit:,.2f}</strong> ({accountType})</p>
    </div>
    <div style="margin-top: 14px;">
      <a href="/console/members/search?memberId={member_id}" class="btn-legacy" id="btn_view_member_profile" style="text-decoration:none; display:inline-block;">View Member Profile</a>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


def start_server(host: str = "127.0.0.1", port: int = 8080):
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
