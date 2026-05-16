#include <complex>

#include <cmath>

#include <iostream>

#include <vector>

#include <algorithm>

using namespace std;

const double EPS = 1e-7;

struct P{

	double x,y,z;

	P(double x,double y,double z) : x(x) , y(y) , z(z) {}

	P(){}

};

P operator + (P a,P b){

	a.x += b.x;

	a.y += b.y;

	a.z += b.z;

	return a;

}

P operator - (P a,P b){

	a.x -= b.x;

	a.y -= b.y;

	a.z -= b.z;

	return a;

}

double abs(P a){

	return sqrt(a.x * a.x + a.y * a.y + a.z * a.z);

}

double det(vector< vector<double> > A){

	double ans = 1;

	for(int i = 0 ; i < A.size() ; i++){

		for(int j = i+1 ; j < A.size() ; j++){

			if( A[i][i] == 0 && A[j][i] != 0 ){

				swap(A[i],A[j]);

				ans *= -1;

				break;

			}

		}

		if( abs(A[i][i]) < 1e-9 ) return 0;

		ans *= A[i][i];

		for(int j = i+1 ; j < A.size() ; j++){

			for(int k = A.size()-1 ; k >= i ; k--){

				A[j][k] -= A[i][k] * A[j][i] / A[i][i];

			}

		}

	}

	return ans;

}



P calc(double k,P a){

	a.x *= k;

	a.y *= k;

	a.z *= k;

	return a;

}

double area(P a,P b,P c){

	b = b-a;

	c = c-a;

	double x = det({{b.y,b.z},{c.y,c.z}});

	double y = det({{b.z,b.x},{c.z,c.x}});

	double z = det({{b.x,b.y},{c.x,c.y}});

	return sqrt(x*x+y*y+z*z);

}

int main(){

	P uaz,ene,a,b,c;

	P vec;

	cin >> uaz.x >> uaz.y >> uaz.z;

	cin >> ene.x >> ene.y >> ene.z;

	cin >> a.x >> a.y >> a.z;

	cin >> b.x >> b.y >> b.z;

	cin >> c.x >> c.y >> c.z;

	

	uaz = uaz - a;

	ene = ene - a;

	b = b - a;

	c = c - a;

	a = a - a;

	vec = ene - uaz;

	double s = abs(vec);

	vec.x /= s;

	vec.y /= s;

	vec.z /= s;

	double l = -1000000 , r = 1000000;

	for( int _ = 0 ; _ < 128 ; _++ ){

		double m = (l+r) / 2.0;

		P pos1 = calc(m,vec) + uaz;

		P pos2 = calc(r,vec) + uaz;

		double D1 = det({{b.x,b.y,b.z},{c.x,c.y,c.z},{pos1.x,pos1.y,pos1.z}});

		double D2 = det({{b.x,b.y,b.z},{c.x,c.y,c.z},{pos2.x,pos2.y,pos2.z}});

		if( D1 * D2 > 0  ){

			r = m;

		}else{

			l = m;

		}

	}

	P hit = calc(l,vec) + uaz;

	//cout << fabs(abs(uaz-hit)-l) << endl;

	//while( abs(det({{b.x,b.y,b.z},{c.x,c.y,c.z},{hit.x,hit.y,hit.z}})) > EPS ){}

	//cout << hit.x << " " << hit.y << " " << hit.z << endl;

	if( l > EPS && fabs(abs(uaz-hit)-l)<EPS && fabs( abs(ene-hit) - (s-l) ) < EPS  ){

		double all = area(a,b,c);

		double sub1 = area(a,b,hit);

		double sub2 = area(b,c,hit);

		double sub3 = area(c,a,hit);

		//cout << all << " " <<  sub1 + sub2 + sub3 << endl;

		if( fabs( all-(sub1+sub2+sub3) ) < EPS ){

			cout << "MISS" << endl;

		}else{

			cout << "HIT" << endl;

		}

	}else{

		cout << "HIT" << endl;

	}

	

	

}