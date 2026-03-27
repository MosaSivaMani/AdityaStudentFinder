from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

@app.route("/api/student", methods=["GET"])
def get_student():
    rollno = request.args.get("rollno", "").strip()
    name = request.args.get("name", "").strip()
    campus = request.args.get("campus", "aec").strip().lower()
    if not rollno and not name:
        return jsonify({"error": "Roll number or name is required"}), 400

    campus_urls = {
        "aec": "https://info.aec.edu.in/aec/olpayment.aspx",
        "acet": "https://info.aec.edu.in/acet/olpayment.aspx",
    }
    url = campus_urls.get(campus, campus_urls["aec"])
    session = requests.Session()

    try:
        # Step 1: GET the page to extract ASP.NET tokens
        page = session.get(url, timeout=10)
        soup = BeautifulSoup(page.text, "html.parser")

        viewstate = soup.find("input", {"id": "__VIEWSTATE"})["value"]
        generator = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"]
        validation = soup.find("input", {"id": "__EVENTVALIDATION"})["value"]

        # Step 2: POST with roll number or name to search
        data = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": generator,
            "__EVENTVALIDATION": validation,
            "txtrollno": rollno if rollno else "",
            "txtname": name if name else "",
            "txtmobile": "",
            "btnsearch": "Search",
        }

        result = session.post(url, data=data, timeout=10)
        soup = BeautifulSoup(result.text, "html.parser")

        # Parse the results table from divresult
        div = soup.find("div", {"id": "divresult"})
        if not div:
            return jsonify({"error": "No results found"}), 404

        table = div.find("table")
        if not table:
            return jsonify({"error": "No results found"}), 404

        rows = table.find_all("tr")
        if len(rows) < 2:
            return jsonify({"error": "No results found"}), 404

        # Extract headers
        headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

        # Extract all matching student rows
        students = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if cells:
                student = {}
                for i, val in enumerate(cells):
                    key = headers[i] if i < len(headers) else f"col_{i}"
                    student[key] = val
                students.append(student)

        if not students:
            return jsonify({"error": "No results found"}), 404

        return jsonify({"students": students, "headers": headers})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_aspnet_tokens(soup):
    return {
        "__VIEWSTATE": soup.find("input", {"id": "__VIEWSTATE"})["value"],
        "__VIEWSTATEGENERATOR": soup.find("input", {"id": "__VIEWSTATEGENERATOR"})["value"],
        "__EVENTVALIDATION": soup.find("input", {"id": "__EVENTVALIDATION"})["value"],
    }


@app.route("/api/student/full", methods=["GET"])
def get_student_full():
    """Login to exam portal and fetch full student details including unmasked mobile, DOB, etc."""
    rollno = request.args.get("rollno", "").strip()
    campus = request.args.get("campus", "aec").strip().lower()
    if not rollno:
        return jsonify({"error": "Roll number is required"}), 400

    exam_urls = {
        "aec": "https://examsection.aec.edu.in/",
        "acet": "https://examsection.acet.ac.in/",
    }
    base_url = exam_urls.get(campus)
    if not base_url:
        return jsonify({"error": f"Exam portal not available for {campus} campus"}), 400

    session = requests.Session()

    try:
        # Step 1: GET main page
        r = session.get(base_url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        tokens = get_aspnet_tokens(soup)

        # Step 2: Click Student Login
        tokens["__EVENTTARGET"] = "lnkStudent"
        tokens["__EVENTARGUMENT"] = ""
        r2 = session.post(base_url, data=tokens, timeout=10)
        soup2 = BeautifulSoup(r2.text, "html.parser")
        tokens2 = get_aspnet_tokens(soup2)

        # Step 3: Login with roll number (password = uppercase roll)
        tokens2["txtUserId"] = rollno
        tokens2["txtPwd"] = rollno.upper()
        tokens2["btnLogin"] = "Login"
        r3 = session.post(base_url, data=tokens2, timeout=10, allow_redirects=True)
        soup3 = BeautifulSoup(r3.text, "html.parser")

        # Check login success
        if "MainStud.aspx" not in r3.url:
            return jsonify({"error": "Login failed. Invalid roll number."}), 401

        # Step 4: Click Basic Information
        tokens3 = get_aspnet_tokens(soup3)
        tokens3["__EVENTTARGET"] = "ctl00$lnkStuInfo"
        tokens3["__EVENTARGUMENT"] = ""
        r4 = session.post(r3.url, data=tokens3, timeout=10, allow_redirects=True)
        soup4 = BeautifulSoup(r4.text, "html.parser")

        # Extract student details from input value attributes
        field_map = {
            "ctl00_cpStudCorner_txtHTNo": "Hall Ticket No",
            "ctl00_cpStudCorner_txtName": "Name",
            "ctl00_cpStudCorner_txtParentName": "Father Name",
            "ctl00_cpStudCorner_txtMotherName": "Mother Name",
            "ctl00_cpStudCorner_txtDOB": "Date of Birth",
            "ctl00_cpStudCorner_txtBatch": "Batch",
            "ctl00_cpStudCorner_txtAdminDate": "Admission Date",
            "ctl00_cpStudCorner_txtCasteCategory": "Caste Category",
            "ctl00_cpStudCorner_txtStuEmail": "Student Email",
            "ctl00_cpStudCorner_txtParentMblNo": "Parent Mobile No",
            "ctl00_cpStudCorner_txtAadharNo": "Aadhar No",
            "ctl00_cpStudCorner_txtABCID": "ABC ID",
        }

        # Also get branch and semester from header
        details = {}
        branch_el = soup4.find("span", {"id": "ctl00_lblBranch"})
        sem_el = soup4.find("span", {"id": "ctl00_lblSem"})
        if branch_el:
            details["Branch"] = branch_el.get_text(strip=True)
        if sem_el:
            details["Semester"] = sem_el.get_text(strip=True)

        for field_id, label in field_map.items():
            el = soup4.find("input", {"id": field_id})
            if el:
                details[label] = el.get("value", "")

        if not details.get("Name"):
            return jsonify({"error": "Could not fetch student details"}), 404

        return jsonify({"details": details})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5050)
