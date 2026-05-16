#include<bits/stdc++.h>

using namespace std;





const int INF = 1e9+5;



int main(){

    int n,k;

    cin>>n>>k;

    vector<int> h(n);

    for(int& x : h) scanf("%d", &x);



    vector<int> dp(n, INF);

    dp[0]=0;

    for(int i=0; i<n; i++){

        for(int j=i+1; j<=i+k; j++){

            if(j<n)

                dp[j]=min(dp[j], dp[i]+abs(h[j]-h[i]));

            else break;

        }

    }



    cout<<dp[n-1];

}