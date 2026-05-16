#include<bits/stdc++.h>

using namespace std;



int main()

{

	int a,b,c;

	bool flag=false;

	cin>>a>>b>>c;

	for(int i=0;i<10000000;i++)

	{

		if((a*i)%b==c%b)

		{

			flag=true;

			break;

		}

	}

	if(flag==true)cout<<"YES\n";

	else cout<<"NO\n";

//	if(a%b==c%b || c%b==0)

//	{

//		cout<<"YES\n";

//	}

//	else

//	{

//		bool flag=false;

//		int hit=0,sum=a;

//		while(1)

//		{

//			hit++;

////			a+=a;

//			sum+=a;

//			if(sum%b==c%b){

//				flag=true;

//				break;

//			}

//			if(sum>b && hit>=10)break;

//		}

//		if(flag==true)cout<<"YES\n";

//		else cout<<"NO\n";

//	}

//

//	

	return 0;

}