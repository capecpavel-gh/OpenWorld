// Copyright Epic Games, Inc. All Rights Reserved.

#include "OpenWorldCharacter.h"
#include "Engine/LocalPlayer.h"
#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/Controller.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputActionValue.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "InputCoreTypes.h"
#include "GameFramework/PlayerController.h"
#include "OpenWorld.h"

AOpenWorldCharacter::AOpenWorldCharacter()
{
	// Set size for collision capsule
	GetCapsuleComponent()->InitCapsuleSize(42.f, 96.0f);
		
	// Don't rotate when the controller rotates. Let that just affect the camera.
	bUseControllerRotationPitch = false;
	bUseControllerRotationYaw = false;
	bUseControllerRotationRoll = false;

	// Configure character movement
	GetCharacterMovement()->bOrientRotationToMovement = true;
	GetCharacterMovement()->RotationRate = FRotator(0.0f, 500.0f, 0.0f);

	// Note: For faster iteration times these variables, and many more, can be tweaked in the Character Blueprint
	// instead of recompiling to adjust them
	GetCharacterMovement()->JumpZVelocity = 500.f;
	GetCharacterMovement()->AirControl = 0.35f;
	GetCharacterMovement()->MaxWalkSpeed = 500.f;
	GetCharacterMovement()->MinAnalogWalkSpeed = 20.f;
	GetCharacterMovement()->BrakingDecelerationWalking = 2000.f;
	GetCharacterMovement()->BrakingDecelerationFalling = 1500.0f;

	// Create a camera boom (pulls in towards the player if there is a collision)
	CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
	CameraBoom->SetupAttachment(RootComponent);
	CameraBoom->TargetArmLength = 400.0f;
	CameraBoom->bUsePawnControlRotation = true;

	// Create a follow camera
	FollowCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("FollowCamera"));
	FollowCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
	FollowCamera->bUsePawnControlRotation = false;

	// Note: The skeletal mesh and anim blueprint references on the Mesh component (inherited from Character)
	// are set in the derived blueprint asset named ThirdPersonCharacter (to avoid direct content references in C++)

	// Needed for smooth zoom and "both buttons = walk forward"
	PrimaryActorTick.bCanEverTick = true;
}

void AOpenWorldCharacter::BeginPlay()
{
	Super::BeginPlay();

	DefaultRotationRateYaw = GetCharacterMovement()->RotationRate.Yaw;

	// Start from the arm length set in the Blueprint, within the zoom limits
	SetZoomDistance(CameraBoom->TargetArmLength, true);
}

void AOpenWorldCharacter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	// Smooth zoom
	if (!FMath::IsNearlyEqual(CameraBoom->TargetArmLength, TargetZoomDistance, 0.1f))
	{
		CameraBoom->TargetArmLength = ZoomInterpSpeed > 0.f
			? FMath::FInterpTo(CameraBoom->TargetArmLength, TargetZoomDistance, DeltaSeconds, ZoomInterpSpeed)
			: TargetZoomDistance;
	}

	// Both mouse buttons held: walk forward in the camera direction
	if (bBothButtonsMoveForward && bCameraRotating && bCameraOrbiting)
	{
		DoMove(0.f, 1.f);
	}
}

void AOpenWorldCharacter::SetZoomDistance(float Distance, bool bInstant)
{
	TargetZoomDistance = FMath::Clamp(Distance, MinZoomDistance, FMath::Max(MinZoomDistance, MaxZoomDistance));

	if (bInstant)
	{
		CameraBoom->TargetArmLength = TargetZoomDistance;
	}
}

void AOpenWorldCharacter::SetupCameraInput()
{
	// Create default camera actions so the project works without extra input assets.
	// Any of these can be replaced by real assets in the character Blueprint.
	if (!CameraZoomAction)
	{
		CameraZoomAction = NewObject<UInputAction>(this, TEXT("IA_CameraZoom_Runtime"));
		CameraZoomAction->ValueType = EInputActionValueType::Axis1D;
	}

	if (!CameraRotateAction)
	{
		CameraRotateAction = NewObject<UInputAction>(this, TEXT("IA_CameraRotate_Runtime"));
		CameraRotateAction->ValueType = EInputActionValueType::Boolean;
	}

	if (!CameraOrbitAction)
	{
		CameraOrbitAction = NewObject<UInputAction>(this, TEXT("IA_CameraOrbit_Runtime"));
		CameraOrbitAction->ValueType = EInputActionValueType::Boolean;
	}

	if (!CameraMappingContext)
	{
		CameraMappingContext = NewObject<UInputMappingContext>(this, TEXT("IMC_Camera_Runtime"));
		CameraMappingContext->MapKey(CameraZoomAction, EKeys::MouseWheelAxis);
		CameraMappingContext->MapKey(CameraRotateAction, EKeys::RightMouseButton);
		CameraMappingContext->MapKey(CameraOrbitAction, EKeys::LeftMouseButton);
	}

	if (const APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Subsystem = ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
		{
			if (!Subsystem->HasMappingContext(CameraMappingContext))
			{
				Subsystem->AddMappingContext(CameraMappingContext, CameraMappingPriority);
			}
		}
	}
}

void AOpenWorldCharacter::MouseLook(const FInputActionValue& Value)
{
	// The mouse only moves the camera while a camera button is held; otherwise it moves the cursor
	if (IsCameraControlActive())
	{
		Look(Value);
	}
}

void AOpenWorldCharacter::CameraZoom(const FInputActionValue& Value)
{
	// Wheel up (positive) zooms in
	SetZoomDistance(TargetZoomDistance - Value.Get<float>() * ZoomStep);
}

void AOpenWorldCharacter::CameraRotateStarted()
{
	bCameraRotating = true;
	UpdateRotationMode();
}

void AOpenWorldCharacter::CameraRotateCompleted()
{
	bCameraRotating = false;
	UpdateRotationMode();
}

void AOpenWorldCharacter::CameraOrbitStarted()
{
	bCameraOrbiting = true;
	UpdateRotationMode();
}

void AOpenWorldCharacter::CameraOrbitCompleted()
{
	bCameraOrbiting = false;
	UpdateRotationMode();
}

void AOpenWorldCharacter::UpdateRotationMode()
{
	// Right button held: the character turns to face where the camera looks (and A/D strafe).
	// Left button only: the camera orbits freely and the character keeps its own facing.
	const bool bFaceCamera = bCameraRotating;

	UCharacterMovementComponent* Movement = GetCharacterMovement();
	Movement->bOrientRotationToMovement = !bFaceCamera;
	Movement->bUseControllerDesiredRotation = bFaceCamera;
	Movement->RotationRate.Yaw = bFaceCamera ? FaceCameraRotationRate : DefaultRotationRateYaw;
}

void AOpenWorldCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	// Set up action bindings
	if (UEnhancedInputComponent* EnhancedInputComponent = Cast<UEnhancedInputComponent>(PlayerInputComponent)) {
		
		// Jumping
		EnhancedInputComponent->BindAction(JumpAction, ETriggerEvent::Started, this, &ACharacter::Jump);
		EnhancedInputComponent->BindAction(JumpAction, ETriggerEvent::Completed, this, &ACharacter::StopJumping);

		// Moving
		EnhancedInputComponent->BindAction(MoveAction, ETriggerEvent::Triggered, this, &AOpenWorldCharacter::Move);
		EnhancedInputComponent->BindAction(MouseLookAction, ETriggerEvent::Triggered, this, &AOpenWorldCharacter::MouseLook);

		// Looking (gamepad right stick, always active)
		EnhancedInputComponent->BindAction(LookAction, ETriggerEvent::Triggered, this, &AOpenWorldCharacter::Look);

		// MMO-style camera: wheel zoom, right button rotate, left button orbit
		SetupCameraInput();
		EnhancedInputComponent->BindAction(CameraZoomAction, ETriggerEvent::Triggered, this, &AOpenWorldCharacter::CameraZoom);
		EnhancedInputComponent->BindAction(CameraRotateAction, ETriggerEvent::Started, this, &AOpenWorldCharacter::CameraRotateStarted);
		EnhancedInputComponent->BindAction(CameraRotateAction, ETriggerEvent::Completed, this, &AOpenWorldCharacter::CameraRotateCompleted);
		EnhancedInputComponent->BindAction(CameraOrbitAction, ETriggerEvent::Started, this, &AOpenWorldCharacter::CameraOrbitStarted);
		EnhancedInputComponent->BindAction(CameraOrbitAction, ETriggerEvent::Completed, this, &AOpenWorldCharacter::CameraOrbitCompleted);
	}
	else
	{
		UE_LOG(LogOpenWorld, Error, TEXT("'%s' Failed to find an Enhanced Input component! This template is built to use the Enhanced Input system. If you intend to use the legacy system, then you will need to update this C++ file."), *GetNameSafe(this));
	}
}

void AOpenWorldCharacter::Move(const FInputActionValue& Value)
{
	// input is a Vector2D
	FVector2D MovementVector = Value.Get<FVector2D>();

	// route the input
	DoMove(MovementVector.X, MovementVector.Y);
}

void AOpenWorldCharacter::Look(const FInputActionValue& Value)
{
	// input is a Vector2D
	FVector2D LookAxisVector = Value.Get<FVector2D>();

	// route the input
	DoLook(LookAxisVector.X, LookAxisVector.Y);
}

void AOpenWorldCharacter::DoMove(float Right, float Forward)
{
	if (GetController() != nullptr)
	{
		// find out which way is forward
		const FRotator Rotation = GetController()->GetControlRotation();
		const FRotator YawRotation(0, Rotation.Yaw, 0);

		// get forward vector
		const FVector ForwardDirection = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::X);

		// get right vector 
		const FVector RightDirection = FRotationMatrix(YawRotation).GetUnitAxis(EAxis::Y);

		// add movement 
		AddMovementInput(ForwardDirection, Forward);
		AddMovementInput(RightDirection, Right);
	}
}

void AOpenWorldCharacter::DoLook(float Yaw, float Pitch)
{
	if (GetController() != nullptr)
	{
		// add yaw and pitch input to controller
		AddControllerYawInput(Yaw);
		AddControllerPitchInput(Pitch);
	}
}

void AOpenWorldCharacter::DoJumpStart()
{
	// signal the character to jump
	Jump();
}

void AOpenWorldCharacter::DoJumpEnd()
{
	// signal the character to stop jumping
	StopJumping();
}
