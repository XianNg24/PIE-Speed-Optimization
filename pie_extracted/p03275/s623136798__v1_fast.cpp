#include <iostream>

#include <algorithm>

#include <cstdio>

#include <cmath>

#include <cstring>

#define ll long long

#define INF 1000000007

using namespace std;



const int MAXN=1e5+5;



int n,l,r;

ll cnt,sum;

int a[MAXN],b[MAXN],c[MAXN];



void work(int begin,int end){

	if(begin==end)

		return;

	int mid=(begin+end)/2;

	work(begin,mid);

	work(mid+1,end);

	int i=begin,j=mid+1,k=begin;

	while(i<=mid && j<=end){

		if(b[i]<b[j])

			c[k++]=b[i++];

		else{

			cnt+=(i-begin);

			c[k++]=b[j++];

		}

	}

	while(i<=mid)

		c[k++]=b[i++];

	while(j<=end){

		cnt+=(i-begin);

		c[k++]=b[j++];

	}

	for(int l=begin;l<=end;l++)

		b[l]=c[l];

}



bool check(int m){

	cnt=0;

	for(int i=1;i<=n;i++){

		if(a[i]<=m)

			b[i]=1;

		else

			b[i]=-1;

	}

	for(int i=1;i<=n;i++){

		b[i]+=b[i-1];

	}

	work(0,n);

	if(cnt>=(sum/2+1))

		return true;

	return false;

}



int main(){

	scanf("%d",&n);

	l=INF;r=0;sum=0;

	for(int i=1;i<=n;i++){

		scanf("%d",&a[i]);

		l=min(l,a[i]);

		r=max(r,a[i]);

		sum+=i;

	}

	while(l<r){

		int m=(l+r)/2;

		if(check(m)){

			r=m;

		}else{

			l=m+1;

		}

	}

	printf("%d\n",r);

	return 0;

}


