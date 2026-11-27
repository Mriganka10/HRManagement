# Onboarding: from selected candidate to employee

`services/onboarding.py`

## Flow

1. **Selection.** The interview is passed with `HRM_AUTO_SELECT=true`, or HR clicks **Select**. The application moves to `selected` and an onboarding record is created.
2. **Prefill from the resume.** The stored resume is parsed again and these fields are filled in:
   - full name and phone
   - city (as the current address)
   - LinkedIn
   - skills (canonicalised)
   - education rows (degree, institution, year, score)
   - work experience (title, company, period, highlights)
   - certifications

   The **offer** comes from the job opening: designation, department, location, employment type, CTC, and a date of joining two weeks out (next Monday).
3. **Selection email.** It contains a **Complete onboarding** link.
4. **Candidate review** in the careers portal.
   - Prefilled fields are marked **from your resume** and can be edited. Education and experience rows can be added or removed.
   - The candidate adds date of birth, gender, blood group, emergency contact, PAN and bank details.
   - **Save draft** keeps the work in progress.
5. **Validation**:
   - required fields are present
   - phone numbers have 10 or more digits
   - age is between 18 and 70
   - PAN format `ABCDE1234F`
   - IFSC format `ABCD0XXXXXX`
   - account number is 9–18 digits
   - at least one skill
   - the accuracy declaration is ticked
6. **Submission**, as one guarded operation: the record is claimed `pending → processing` so a double click cannot create two employees. Then:
   - the **employee record** is created with Employee ID `KZE####`, `probation` status and `probation_end` set to joining date + `HRM_PROBATION_MONTHS`;
   - the **employee account** is created with user ID = Employee ID and a random 12-character temporary password (`must_change_password`);
   - the **salary structure** is created from the offer CTC;
   - the application moves to `hired`;
   - the **welcome email** carries the user ID and temporary password;
   - HR gets an in-app notification.
7. **First sign-in.** At `/login` the employee must set their own password. Changing it signs out every other session. Their employee portal is then fully set up: leave balances pro-rated from the joining date, policies, the assistant and their profile.

If anything fails during step 6, the record goes back to `pending` and the candidate can submit again.

## HR view

* **HR → Onboarding** lists every selected candidate: waiting or completed, with the Employee ID and joining date.
* The employee then appears in **HR → Employees**. HR assigns the reporting manager, adjusts designation, department or joining date, sets monthly TDS and generates documents.

## Adding existing staff

**HR → Employees → Add employee** creates the employee record, account and salary structure directly, and emails the credentials. Use it for people who joined before the portal existed.
