import requests
import sys
import json
import os
from datetime import datetime
import base64
from io import BytesIO
from PIL import Image

class EcoCropAPITester:
    def __init__(self, base_url="https://crophealth-guru.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED")
        else:
            print(f"❌ {name} - FAILED: {details}")
        
        self.test_results.append({
            "test": name,
            "success": success,
            "details": details
        })

    def run_test(self, name, method, endpoint, expected_status, data=None, files=None, headers=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        
        if self.token:
            test_headers['Authorization'] = f'Bearer {self.token}'
        
        if headers:
            test_headers.update(headers)
        
        if files:
            # Remove Content-Type for multipart/form-data
            test_headers.pop('Content-Type', None)

        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers)
            elif method == 'POST':
                if files:
                    response = requests.post(url, data=data, files=files, headers=test_headers)
                else:
                    response = requests.post(url, json=data, headers=test_headers)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers)

            success = response.status_code == expected_status
            details = f"Status: {response.status_code}"
            
            if not success:
                try:
                    error_data = response.json()
                    details += f", Error: {error_data.get('detail', 'Unknown error')}"
                except:
                    details += f", Response: {response.text[:200]}"
            
            self.log_test(name, success, details)
            
            if success:
                try:
                    return response.json()
                except:
                    return {}
            return None

        except Exception as e:
            self.log_test(name, False, f"Exception: {str(e)}")
            return None

    def test_user_registration(self):
        """Test user registration"""
        timestamp = datetime.now().strftime('%H%M%S')
        test_data = {
            "email": f"test_user_{timestamp}@ecocrop.ai",
            "name": f"Test User {timestamp}",
            "password": "testpass123"
        }
        
        result = self.run_test(
            "User Registration",
            "POST",
            "auth/register",
            200,
            data=test_data
        )
        
        if result and 'token' in result:
            self.token = result['token']
            self.user_id = result['user']['id']
            return True
        return False

    def test_user_login(self):
        """Test user login with existing credentials"""
        # First register a user
        timestamp = datetime.now().strftime('%H%M%S')
        register_data = {
            "email": f"login_test_{timestamp}@ecocrop.ai",
            "name": f"Login Test {timestamp}",
            "password": "loginpass123"
        }
        
        # Register user
        register_result = self.run_test(
            "User Registration for Login Test",
            "POST",
            "auth/register",
            200,
            data=register_data
        )
        
        if not register_result:
            return False
        
        # Now test login
        login_data = {
            "email": register_data["email"],
            "password": register_data["password"]
        }
        
        result = self.run_test(
            "User Login",
            "POST",
            "auth/login",
            200,
            data=login_data
        )
        
        return result is not None

    def test_invalid_login(self):
        """Test login with invalid credentials"""
        invalid_data = {
            "email": "nonexistent@example.com",
            "password": "wrongpassword"
        }
        
        result = self.run_test(
            "Invalid Login",
            "POST",
            "auth/login",
            401,
            data=invalid_data
        )
        
        return result is None  # Should fail with 401

    def test_get_user_profile(self):
        """Test getting current user profile"""
        if not self.token:
            self.log_test("Get User Profile", False, "No token available")
            return False
        
        result = self.run_test(
            "Get User Profile",
            "GET",
            "auth/me",
            200
        )
        
        return result is not None

    def test_unauthorized_access(self):
        """Test accessing protected endpoint without token"""
        # Temporarily remove token
        temp_token = self.token
        self.token = None
        
        result = self.run_test(
            "Unauthorized Access",
            "GET",
            "auth/me",
            403  # Changed from 401 to 403 as FastAPI returns 403
        )
        
        # Restore token
        self.token = temp_token
        
        return result is None  # Should fail with 403

    def create_test_image(self):
        """Create a test image for upload"""
        # Create a simple test image
        img = Image.new('RGB', (100, 100), color='green')
        img_buffer = BytesIO()
        img.save(img_buffer, format='JPEG')
        img_buffer.seek(0)
        return img_buffer

    def test_crop_analysis_without_image(self):
        """Test crop analysis without image upload"""
        if not self.token:
            self.log_test("Crop Analysis Without Image", False, "No token available")
            return False
        
        analysis_data = {
            'crop_name': 'Tomato',
            'growth_stage': 'Flowering',
            'symptoms': 'Yellowing leaves with brown spots',
            'soil_moisture': '45',
            'temperature': '25.5',
            'humidity': '70'
        }
        
        # Use form data instead of JSON for this endpoint
        url = f"{self.api_url}/analysis"
        headers = {'Authorization': f'Bearer {self.token}'}
        
        try:
            response = requests.post(url, data=analysis_data, headers=headers)
            success = response.status_code == 200
            details = f"Status: {response.status_code}"
            
            if not success:
                try:
                    error_data = response.json()
                    details += f", Error: {error_data.get('detail', 'Unknown error')}"
                except:
                    details += f", Response: {response.text[:200]}"
            
            self.log_test("Crop Analysis Without Image", success, details)
            
            if success:
                result = response.json()
                if 'id' in result:
                    self.analysis_id = result['id']
                    return True
            return False
            
        except Exception as e:
            self.log_test("Crop Analysis Without Image", False, f"Exception: {str(e)}")
            return False

    def test_crop_analysis_with_image(self):
        """Test crop analysis with image upload"""
        if not self.token:
            self.log_test("Crop Analysis With Image", False, "No token available")
            return False
        
        analysis_data = {
            'crop_name': 'Wheat',
            'growth_stage': 'Vegetative',
            'symptoms': 'Rust-colored spots on leaves',
            'soil_moisture': '30',
            'temperature': '22.0',
            'humidity': '65'
        }
        
        # Create test image
        test_image = self.create_test_image()
        files = {'image': ('test_crop.jpg', test_image, 'image/jpeg')}
        
        result = self.run_test(
            "Crop Analysis With Image",
            "POST",
            "analysis",
            200,
            data=analysis_data,
            files=files
        )
        
        return result is not None

    def test_get_analysis_history(self):
        """Test getting analysis history"""
        if not self.token:
            self.log_test("Get Analysis History", False, "No token available")
            return False
        
        result = self.run_test(
            "Get Analysis History",
            "GET",
            "analysis/history",
            200
        )
        
        return result is not None

    def test_get_analysis_detail(self):
        """Test getting specific analysis detail"""
        if not self.token:
            self.log_test("Get Analysis Detail", False, "No token available")
            return False
        
        if not hasattr(self, 'analysis_id'):
            self.log_test("Get Analysis Detail", False, "No analysis ID available")
            return False
        
        result = self.run_test(
            "Get Analysis Detail",
            "GET",
            f"analysis/{self.analysis_id}",
            200
        )
        
        return result is not None

    def test_get_nonexistent_analysis(self):
        """Test getting non-existent analysis"""
        if not self.token:
            self.log_test("Get Non-existent Analysis", False, "No token available")
            return False
        
        fake_id = "nonexistent-analysis-id"
        result = self.run_test(
            "Get Non-existent Analysis",
            "GET",
            f"analysis/{fake_id}",
            404
        )
        
        return result is None  # Should fail with 404

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting EcoCrop AI Backend API Tests")
        print(f"📍 Testing against: {self.base_url}")
        print("=" * 60)
        
        # Authentication Tests
        print("\n🔐 Authentication Tests")
        self.test_user_registration()
        self.test_user_login()
        self.test_invalid_login()
        self.test_get_user_profile()
        self.test_unauthorized_access()
        
        # Analysis Tests
        print("\n🌱 Crop Analysis Tests")
        self.test_crop_analysis_without_image()
        self.test_crop_analysis_with_image()
        self.test_get_analysis_history()
        self.test_get_analysis_detail()
        self.test_get_nonexistent_analysis()
        
        # Print Results
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            print("❌ Some tests failed!")
            print("\nFailed Tests:")
            for result in self.test_results:
                if not result['success']:
                    print(f"  - {result['test']}: {result['details']}")
            return 1

def main():
    tester = EcoCropAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())